"""The configiq step (configiq_night.py): pinned fetch, and the arguments of the scoring run (design D9)."""
import hashlib
import io
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import configiq_night as cn  # noqa: E402

REF = "a" * 40


def _sources(tmp_path, assets):
    led = tmp_path / "substrate" / "catalog" / "ledger"
    led.mkdir(parents=True)
    rows = "".join(f"          - {{name: {n}, sha256: \"{h}\"}}\n" for n, h in assets)
    (led / "sources.yaml").write_text(
        "sources:\n  - id: other\n    revision: {ref: zzz, assets: []}\n"
        f"  - id: configiq\n    revision:\n      ref: {REF}\n      assets:\n" + rows)
    return led


def _opener(files):
    def op(url):
        for name, data in files.items():
            if url.endswith("/" + name):
                return io.BytesIO(data)
        raise OSError(url)
    return op


def test_pins_reads_only_the_configiq_source(tmp_path):
    led = _sources(tmp_path, [("manifest.json", "00" * 32)])
    assert cn.pins(led / "sources.yaml") == (REF, [("manifest.json", "00" * 32)])


def test_fetch_writes_files_whose_sha256_is_pinned(tmp_path):
    data = b"rows"
    want = hashlib.sha256(data).hexdigest()
    cn.fetch(REF, [("pairs/x/ground_truth.parquet", want)], tmp_path / "d", opener=_opener({"ground_truth.parquet": data}))
    assert (tmp_path / "d" / "pairs/x/ground_truth.parquet").read_bytes() == data


def test_fetch_refuses_a_file_whose_sha256_differs_and_writes_nothing(tmp_path):
    with pytest.raises(cn.NightError, match="not the pinned"):
        cn.fetch(REF, [("manifest.json", "00" * 32)], tmp_path / "d", opener=_opener({"manifest.json": b"changed"}))
    assert not (tmp_path / "d" / "manifest.json").exists()


def _args(tmp_path, **extra):
    a = ["--substrate", str(tmp_path / "substrate"), "--blis", "b", "--catalog", "c", "--registry", "r", "--fields", "f",
         "--substrate-version", "v0.15.0", "--sim-build", "v0.18.0", "--harness-commit", "c" * 40, "--out", str(tmp_path / "out")]
    for k, v in extra.items():
        a += [f"--{k}", v]
    return a


def test_a_step_that_fails_returns_1_and_never_raises(tmp_path, capsys):
    _sources(tmp_path, [("manifest.json", "00" * 32)])
    assert cn.main(_args(tmp_path, **{"substrate-version": "not-a-pin"})) == 1
    assert "exact pin" in capsys.readouterr().err


def test_every_ledger_unit_is_scored_less_the_left_out_and_none_is_withheld(tmp_path, monkeypatch):
    """D9: score_configiq gets the ledger.yaml (the left-out filter) and no --withhold-split; the funnel gets --ledger-yaml
    and, when named, --published (the guard that no configiq id is in a fit, select or validate list)."""
    led = _sources(tmp_path, [("manifest.json", hashlib.sha256(b"m").hexdigest())])
    monkeypatch.setattr(cn, "fetch", lambda ref, assets, dest, **kw: Path(dest).mkdir(parents=True, exist_ok=True))
    calls = []

    def run(cmd, **kw):
        cmd = [str(c) for c in cmd]
        calls.append(cmd)
        if any(c.endswith("score_configiq.py") for c in cmd):
            out = Path(cmd[cmd.index("--out") + 1])
            out.mkdir(parents=True)
            (out / "summary.json").write_text(json.dumps({"provenance": {"blis": {"commit_sha": "d" * 40}}}))
        if any(c.endswith("funnel.py") for c in cmd):
            Path(cmd[cmd.index("--out") + 1]).write_text(json.dumps({"format": "funnel-2", "funnels": {"configiq": {}}}))
    monkeypatch.setattr(cn, "_run", run)
    assert cn.main(_args(tmp_path, published=str(tmp_path / "pub"))) == 0
    score = next(c for c in calls if any(x.endswith("score_configiq.py") for x in c))
    assert score[score.index("--ledger-yaml") + 1] == str(led / "ledger.yaml")
    assert "--withhold-split" not in score
    assert score[score.index("--catalog-release") + 1] == "v0.15.0"
    funnel = next(c for c in calls if any(x.endswith("funnel.py") for x in c))
    assert funnel[funnel.index("--ledger-yaml") + 1] == str(led / "ledger.yaml")
    assert funnel[funnel.index("--published") + 1] == str(tmp_path / "pub")
    assert "--configiq-points" in funnel
    assert json.loads((tmp_path / "out" / "funnel.json").read_text())["dataset"] == REF  # stamped for the nightly's stale check


def test_stamp_funnel_records_the_dataset_revision_the_nightly_compares(tmp_path):
    f = tmp_path / "funnel.json"
    f.write_text(json.dumps({"format": "funnel-2", "funnels": {"configiq": {}}}))
    cn.stamp_funnel(f, REF)
    assert json.loads(f.read_text())["dataset"] == REF and "funnels" in json.loads(f.read_text())
