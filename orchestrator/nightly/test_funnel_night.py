"""A night publishes the Sources tab's data (funnel.json, format funnel-2) when its contract is the whole of the summary, and
publishes none, removing another snapshot's, when it is not. Offline: the ledger, contract and summary are canned."""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "baseline"))
import funnel as fn  # noqa: E402
import funnel_night as fnn  # noqa: E402

SNAP = "2026-11-23_blis-abc_ix-api-2026-11-23"
FW = ["vllm", "sglang", "vllm", "dynamo-sglang", "trt", "vllm"]


def _night(tmp_path, scored_ids):
    ids = [f"{i:064x}" for i in range(1, 7)]
    lg = SimpleNamespace(units={u: SimpleNamespace(unit_id=u, identity={"framework": FW[k]}) for k, u in enumerate(ids)},
                         by_record={str(k): 1 for k in range(8)}, left_out={})
    contract = tmp_path / "contract"
    contract.mkdir()
    lines = {"fidelity.jsonl": [{"point_id": ids[0], "grade": "G4"}, {"point_id": ids[1], "grade": "G4"}],
             "not_scored.jsonl": [{"point_id": u, "g5_reason": {"code": "value_not_recorded"}} for u in ids[2:5]],
             "failed.jsonl": [{"point_id": ids[5], "faults": ["scorer_error:boom"]}]}
    for name, rows in lines.items():
        keep = [r for r in rows if r["point_id"] in scored_ids]
        (contract / name).write_text("".join(json.dumps(r) + "\n" for r in keep))
    summary = tmp_path / "summary.json"
    summary.write_text(json.dumps({"snapshot_id": SNAP, "coverage": {"points": 6}}))
    return lg, set(ids), contract, summary, ids


def test_a_whole_night_writes_a_funnel_2_file_and_a_delta_night_writes_none_and_drops_another_snapshots(tmp_path):
    lg, anchor, contract, summary, ids = _night(tmp_path, scored_ids=set(_ids_of(6)))
    out = tmp_path / "funnel.json"
    assert fnn.write(out, summary, lambda s: fnn.build(lg, anchor, contract, s)) is None
    doc = fn.validate(json.loads(out.read_text()))
    f = doc["funnels"]["inferencex"]
    assert doc["snapshot_id"] == SNAP and doc["problems"] == []
    assert f["stages"]["in_scope"] == 6 and f["stages"]["scored"] == 2
    assert f["g5"] == {"value_not_recorded": 3} and f["failed"] == {"scorer_error": 1}

    # The contract of a night that merged a delta holds two of the six points: nothing is written, a funnel of an older snapshot
    # is removed, and the reason is returned for the workflow warning.
    (tmp_path / "delta").mkdir()
    lg, anchor, contract, summary, ids = _night(tmp_path / "delta", scored_ids=set(_ids_of(2)))
    out.write_text(json.dumps({**doc, "snapshot_id": "an-older-snapshot"}))
    reason = fnn.write(out, summary, lambda s: fnn.build(lg, anchor, contract, s))
    assert reason and "not the whole" in reason and not out.exists()


def _ids_of(n):
    return [f"{i:064x}" for i in range(1, n + 1)]
