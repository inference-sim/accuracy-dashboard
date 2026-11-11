"""The workload-statement rule (design 11.2, D8, X19): a speculative point's acceptance profile is keyed by the
workload's category and thinking mode. The dashboard states neither on its own. A server's reasoning parser is not a
statement about the prompts it was sent; a speculative point whose acceptance length is neither pinned nor logged and
whose workload states no category is G5 `value_not_recorded:workload_category_not_stated`; a profile the substrate does
not hold for a stated pair is `value_not_recorded:profile_not_available:<category>/<thinking>`.

Run: python3 -m pytest orchestrator/ingest/test_thinking_rule.py
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import fields as fl  # noqa: E402
import score as sc  # noqa: E402
import settings as st  # noqa: E402
import test_score_e2e as e2e  # noqa: E402

S = st.Setting
NO_ACCEPTANCE = e2e.LOG.replace(", 'synthetic_acceptance_length': 2.4", "")
WITH_PARSER = NO_ACCEPTANCE.replace("'tensor_parallel_size': 1,", "'tensor_parallel_size': 1, 'reasoning_parser': 'deepseek_v4',")


def _fields(acceptance_modelled: bool):
    """The fixture's field list with reasoning_parser proven inert (the engine ignores it), and the
    acceptance field modelled or not."""
    doc = json.loads((HERE / "testdata" / "fields" / "fields.json").read_bytes())
    doc["fields"].append({"name": "reasoning_parser", "source": "config", "status": "proven_inert",
                          "evidence": {"proof": "oracle/inertness/reasoning_parser.json"},
                          "estimation": {"rule": "none"}})
    doc["fields"].sort(key=lambda f: (f["name"], f["source"]))
    if not acceptance_modelled:
        for f in doc["fields"]:
            if f["name"] == "speculative_config.synthetic_acceptance_length":
                f.update(status="not_modelled", estimation={"rule": "leave_unset"}, evidence={"issue": "inference-sim/blis-vllm#1"})
    return fl.parse(json.dumps(doc).encode())


def _spec_built(**kw):
    return st.Built(deployment={"pools": [{"engine": {"speculative_config": {"method": "mtp"}}}]}, **kw)


def _rp(value, requested=True):
    s = S("reasoning_parser", value)
    s.requested = requested
    return {"reasoning_parser": s}


def test_a_reasoning_parser_is_never_read_as_a_thinking_mode():
    assert st.recorded_thinking(_rp("deepseek_v4")) is None
    assert sc.thinking_argv(_spec_built()) == []


def test_a_speculative_point_with_no_category_and_no_acceptance_is_named_not_stated():
    b, o = _spec_built(), sc.Outcome("p", {}, {})
    sc.require_workload_category(o, b)
    sc.require_workload_category(o, b)                                # naming it twice is naming it once
    assert o.reasons.count("value_not_recorded:workload_category_not_stated") == 1
    assert b.thinking is None and b.fallback_category is None and not o.subs


def test_the_gap_is_not_named_when_the_workload_states_enough():
    def run(b):
        o = sc.Outcome("p", {}, {})
        sc.require_workload_category(o, b)
        return o.reasons
    assert run(_spec_built(acceptance_length="2.4")) == []             # an acceptance length is pinned or logged
    assert run(_spec_built(fallback_category="coding")) == []          # a requested fallback category
    assert run(st.Built(deployment={"pools": [{"engine": {}}]})) == []   # no speculation: nothing to select


def test_a_scored_speculative_point_with_a_parser_and_no_acceptance_is_not_replayed():
    tmp = Path(tempfile.mkdtemp())
    try:
        entry, env = e2e._setup(tmp, log=WITH_PARSER)
        env.field_list = _fields(acceptance_modelled=False)
        o, _ = e2e._score(tmp, entry, env, tmp / "c1")
        assert o.fidelity is None
        assert "value_not_recorded:workload_category_not_stated" in o.reasons
        assert not e2e._saw(env)
    finally:
        shutil.rmtree(tmp)


def test_a_logged_acceptance_the_engine_models_scores_with_no_mode_or_category_stated():
    tmp = Path(tempfile.mkdtemp())
    try:
        entry, env = e2e._setup(tmp, log=WITH_PARSER + e2e.SPEC_LINES)
        env.field_list = _fields(acceptance_modelled=True)
        o, _ = e2e._score(tmp, entry, env, tmp / "c1")
        assert o.fidelity is not None, o.reasons
        argv = e2e._saw(env)[0]["argv"]
        assert "--speculative-thinking" not in argv and "--speculative-fallback-category" not in argv
        assert not [s for s in o.fidelity["substitutions"] if s["subject"] == "workload.thinking_mode"]
    finally:
        shutil.rmtree(tmp)


def test_the_substrates_missing_profile_is_named_by_its_pair(tmp_path):
    err = ('level=fatal msg="engine: deepseek-v4-pro/mtp/k3/thinking-on/chat acceptance: no profile for '
           'deepseek-v4-pro/mtp/k3/thinking-on/chat in inferencex-golden-al; the workload category chat has none"')
    assert sc.value_refusal(err, tmp_path, None) == "value_not_recorded:profile_not_available:chat/on"


def test_a_requested_fallback_category_is_used_and_named():
    tmp = Path(tempfile.mkdtemp())
    try:
        entry, env = e2e._setup(tmp, log=WITH_PARSER)
        env.field_list = _fields(acceptance_modelled=False)
        env.speculative_fallback_category = "coding"
        o, _ = e2e._score(tmp, entry, env, tmp / "c1")
        assert o.fidelity is not None, o.reasons
        assert [s for s in o.fidelity["substitutions"] if s["subject"] == "workload.category"]
        assert "value_not_recorded:workload_category_not_stated" not in o.reasons
    finally:
        shutil.rmtree(tmp)


def test_the_chat_template_is_assumed_on_for_a_speculative_run_whose_job_log_is_gone():
    """A speculative run's launch scripts pass --use-chat-template, so with the job log gone the assumed client flags
    say so."""
    tmp = Path(tempfile.mkdtemp())
    try:
        entry, env = e2e._setup(tmp, log=WITH_PARSER + e2e.SPEC_LINES, job_log=None)
        env.field_list = _fields(acceptance_modelled=True)
        o, _ = e2e._score(tmp, entry, env, tmp / "c1")
        assert o.fidelity is not None, o.reasons
        flags = [d for d in o.fidelity["requests"]["differences"] if d["subject"] == "client_flags"]
        assert flags and "--use-chat-template" in flags[0]["detail"]
    finally:
        shutil.rmtree(tmp)
