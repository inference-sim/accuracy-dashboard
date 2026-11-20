"""Tests of the recoverable-input count (recoverable.py): how each kind of anchor unit is placed, the guards, the
counting law, and the section the baseline report publishes. Offline: the API is a dict of canned bodies."""
import copy
import io
import json
import sys
import urllib.error
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "ingest"))
import api  # noqa: E402
import ledger as ldg  # noqa: E402
import ledger_fake  # noqa: E402
import m3_baseline as mb  # noqa: E402
import recoverable as rc  # noqa: E402

LOG = "INFO Initializing a V1 LLM engine (v0.11.0) with config: non-default args: {}"


def unit(rid, *, hardware="h200", framework="vllm", benchmark_type="fixed_seq_len"):
    ident = {"hardware": hardware, "framework": framework, "benchmark_type": benchmark_type}
    return ldg.Unit(unit_id=f"{int(rid):064x}", role_key="0" * 64, identity=ident,
                    measurements=[{"record": str(rid), "measured": "0" * 64, "duplicates": [], "merged": [],
                                   "recorded": {}}])


def http(code):
    return urllib.error.HTTPError("u", code, "x", {}, io.BytesIO(b""))


class Api:
    """The API's /server-log: a body per row id, or an HTTP error to raise. Records what was asked."""
    def __init__(self, bodies):
        self.bodies, self.asked = bodies, []

    def __call__(self, url):
        assert url.startswith(api.API + "/server-log?id="), url
        rid = url.rsplit("=", 1)[1]
        self.asked.append(rid)
        body = self.bodies[rid]
        if isinstance(body, int):
            raise http(body)
        return json.dumps(body).encode()


CASES = [
    ("a vLLM single-turn unit whose log the API serves", unit(1), {"1": {"serverLog": LOG}},
     (rc.RECOVERABLE, "api_server_log"), ["1"]),
    ("the API holds no log for the row", unit(2), {"2": 404}, (rc.NOT_RECOVERED, "api_server_log_404"), ["2"]),
    ("the API will not serve the log", unit(3), {"3": 413}, (rc.NOT_RECOVERED, "api_server_log_413"), ["3"]),
    ("the API serves an empty log", unit(4), {"4": {"serverLog": ""}},
     (rc.NOT_RECOVERED, "api_server_log_not_a_log"), ["4"]),
    ("the API serves text that is not a server log", unit(5), {"5": {"serverLog": "hello"}},
     (rc.NOT_RECOVERED, "api_server_log_not_a_log"), ["5"]),
    ("AMD hardware is excluded without a request", unit(6, hardware="mi355x"), {},
     (rc.EXCLUDED, "amd_or_tpu"), []),
    ("TPU hardware is excluded without a request", unit(7, hardware="tpu-v6e"), {},
     (rc.EXCLUDED, "amd_or_tpu"), []),
    ("TRT-LLM has no BLIS engine", unit(8, framework="trt"), {}, (rc.EXCLUDED, "engine_unsupported:trt"), []),
    ("a framework label the table does not name", unit(9, framework="newfw"), {},
     (rc.EXCLUDED, "unknown_framework:newfw"), []),
    ("an agentic unit needs an export no probe reads", unit(10, benchmark_type="agentic_traces"), {},
     (rc.NOT_RECOVERED, "no_probe:agentic_export"), []),
    ("a disaggregated unit needs its recipe", unit(11, framework="vllm-disagg"), {},
     (rc.NOT_RECOVERED, "no_probe:pd_recipe"), []),
    ("an SGLang unit needs its launch command", unit(12, framework="sglang"), {},
     (rc.NOT_RECOVERED, "no_probe:sglang_launch_command"), []),
]


@pytest.mark.parametrize("name,u,bodies,want,asked", CASES, ids=[c[0] for c in CASES])
def test_each_kind_of_unit_is_placed_by_what_its_inputs_need(name, u, bodies, want, asked):
    fetch = Api(bodies)
    assert rc.classify(u, fetch) == want
    assert fetch.asked == asked


def test_a_fault_other_than_the_sources_404_and_413_stops_the_count():
    with pytest.raises(urllib.error.HTTPError):
        rc.classify(unit(1), Api({"1": 503}))


def test_the_kept_record_is_the_one_asked_for_a_unit_of_several_records():
    u = unit(7)
    u.measurements[0]["duplicates"] = ["3"]
    u.measurements.append({"record": "5", "measured": "0" * 64, "duplicates": [], "merged": [], "recorded": {}})
    fetch = Api({"5": {"serverLog": LOG}})
    assert u.kept_record == "5" and rc.classify(u, fetch)[0] == rc.RECOVERABLE
    assert fetch.asked == ["5"]


def test_the_count_adds_up_and_does_not_depend_on_the_order_or_the_workers():
    units = [c[1] for c in CASES]
    bodies = {k: v for c in CASES for k, v in c[2].items()}
    base, per_unit = rc.count(units, Api(bodies))
    assert base == {"anchor_units": 12,
                    "excluded": {"amd_or_tpu": 2, "engine_unsupported:trt": 1, "unknown_framework:newfw": 1},
                    "recoverable": {"api_server_log": 1},
                    "not_recovered": {"api_server_log_404": 1, "api_server_log_413": 1, "api_server_log_not_a_log": 2,
                                      "no_probe:agentic_export": 1, "no_probe:pd_recipe": 1,
                                      "no_probe:sglang_launch_command": 1}}
    t = rc.totals({**base})
    assert t["excluded"] + t["recoverable"] + t["not_recovered"] == base["anchor_units"]
    assert [u for u, _, _ in per_unit] == sorted(u for u, _, _ in per_unit)
    assert rc.count(list(reversed(units)), Api(bodies), workers=4) == (base, per_unit)


def _row(n, **kw):
    return {"id": n, "model": "m", "hardware": "h200", "precision": "fp8", "framework": "vllm",
            "benchmark_type": "fixed_seq_len", "date": "2026-05-01", "run_url": None, "conc": 4, **kw}


def _ledger(tmp_path, rows):
    d = ledger_fake.write(tmp_path / "ledger", rows)
    pub = tmp_path / "anchor.yaml"
    pub.write_text(json.dumps({"kind": "PublishedUnits", "role": "anchor", "partition_version": 1,
                               "seed_sha256": "0" * 64, "units": sorted(ledger_fake.point_id(r) for r in rows)}))
    return d, pub


def test_the_command_writes_the_counts_the_unit_list_and_stays_deterministic(tmp_path, monkeypatch, capsys):
    rows = [_row(1), _row(2, conc=8), _row(3, hardware="mi300x", conc=16), _row(4, framework="trt", conc=32)]
    d, pub = _ledger(tmp_path, rows)
    fetch = Api({"1": {"serverLog": LOG}, "2": 404})
    monkeypatch.setattr(api, "http_fetch", fetch)

    def run(name):
        out, units = tmp_path / f"{name}.json", tmp_path / f"{name}.jsonl"
        assert rc.main(["--ledger", str(d), "--anchor", str(pub), "--today", "2026-11-19", "--out", str(out),
                        "--units-out", str(units), "--workers", "1"]) == 0
        return json.loads(out.read_text()), units.read_text()

    doc, lines = run("a")
    assert (doc["anchor_units"], doc["recoverable"], doc["not_recovered"]) == (
        4, {"api_server_log": 1}, {"api_server_log_404": 1})
    assert doc["excluded"] == {"amd_or_tpu": 1, "engine_unsupported:trt": 1}
    assert doc["checked_on"] == "2026-11-19" and doc["source"]["ledger_revision"] == "test"
    assert len(lines.splitlines()) == 4
    assert run("b") == (doc, lines)
    assert "1 recoverable" in capsys.readouterr().out


def test_an_anchor_list_naming_a_unit_the_ledger_lacks_is_refused(tmp_path):
    d, pub = _ledger(tmp_path, [_row(1)])
    doc = json.loads(pub.read_text())
    doc["units"] = sorted(doc["units"] + ["f" * 64])
    pub.write_text(json.dumps(doc))
    assert rc.main(["--ledger", str(d), "--anchor", str(pub), "--today", "2026-11-19",
                    "--out", str(tmp_path / "o.json")]) == 2
    assert not (tmp_path / "o.json").exists()


def _doc():
    d, per_unit = rc.count([c[1] for c in CASES], Api({k: v for c in CASES for k, v in c[2].items()}))
    d.update(format=rc.FORMAT, checked_on="2026-11-19", source={
        "api": api.BASE, "ledger_revision": "r", "anchor_list_sha256": "a" * 64, "probed": [rc.API_SERVER_LOG],
        "meaning": "Recoverable is a floor."})
    return d


def test_a_document_whose_parts_do_not_add_up_is_refused():
    assert rc.check(_doc())["anchor_units"] == 12
    bad = copy.deepcopy(_doc())
    bad["recoverable"]["api_server_log"] += 1
    with pytest.raises(rc.RecoverableError, match="do not add up"):
        rc.check(bad)
    with pytest.raises(rc.RecoverableError, match="not a recoverable-1"):
        rc.check({"anchor_units": 1})


def test_the_report_section_states_the_count_and_that_it_is_a_floor():
    text = "\n".join(mb._recoverable_markdown(rc.check(_doc())))
    assert "**1 of 8 counted anchor units have recoverable inputs** (12 anchor units, 4 excluded)" in text
    assert "| Recoverable | 1 | `api_server_log` |" in text
    assert "| Not recovered | 1 | `no_probe:pd_recipe` |" in text
    assert "Recoverable is a floor." in text and "2026-11-19" in text


def _report(**extra):
    import os
    import test_m3_baseline as tb
    kw = tb._inputs()
    kw["contract"] = Path("docs/m2/preliminary-after/contract")
    cwd = os.getcwd()
    os.chdir(tb.ROOT)
    try:
        return mb.report(**kw, **extra)[0]
    finally:
        os.chdir(cwd)


def test_the_report_carries_the_count_only_when_it_is_given():
    plain = _report()
    assert "recoverable" not in plain and "recoverable" not in mb.markdown(plain)
    with_count = _report(recoverable=_doc())
    assert with_count["recoverable"] == _doc()
    assert {k: v for k, v in with_count.items() if k != "recoverable"} == plain
    md = mb.markdown(with_count)
    assert md.startswith(mb.markdown(plain).rstrip("\n")) and "## Anchor units whose inputs are recoverable" in md


def test_the_report_refuses_a_count_that_does_not_add_up():
    bad = _doc()
    bad["anchor_units"] += 1
    with pytest.raises(mb.BaselineError, match="do not add up"):
        _report(recoverable=bad)
