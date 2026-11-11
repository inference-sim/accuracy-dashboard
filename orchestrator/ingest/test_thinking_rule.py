"""The thinking-mode rule (design §11.2): a speculative point whose server log records no
acceptance length and no thinking mode, and whose server runs a reasoning parser, is replayed with thinking
`on` and the fallback category `coding`, named as an `estimated` substitution on workload.thinking_mode. A
logged acceptance length that the engine models takes precedence; a server with no parser is given nothing.

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


def test_the_rule_applies_to_a_speculative_point_with_a_parser_and_no_mode_and_no_acceptance():
    b, o = _spec_built(), sc.Outcome("p", {}, {})
    sc.default_thinking(o, b, _rp("deepseek_v4"))
    assert (b.thinking, b.fallback_category) == ("on", "coding")
    assert sc.thinking_argv(b) == ["--speculative-thinking", "on", "--speculative-fallback-category", "coding"]
    [sub] = o.subs
    assert sub["kind"] == "estimated" and sub["subject"] == "workload.thinking_mode"
    assert "deepseek_v4" in sub["detail"] and "thinking on" in sub["detail"] and "coding" in sub["detail"]


def test_the_rule_leaves_every_other_point_alone():
    def run(b, settings):
        o = sc.Outcome("p", {}, {})
        sc.default_thinking(o, b, settings)
        return b, o
    b, o = run(_spec_built(), {})                                    # no parser
    assert b.thinking is None and not o.subs and sc.thinking_argv(b) == []
    b, o = run(_spec_built(), _rp("deepseek_v4", requested=False))   # the engine's own, empty or resolved
    assert b.thinking is None and not o.subs
    b, o = run(_spec_built(), _rp(""))                               # a parser set to nothing
    assert b.thinking is None and not o.subs
    b, o = run(_spec_built(thinking="off"), _rp("deepseek_v4"))      # the run recorded a mode
    assert b.thinking == "off" and not o.subs and b.fallback_category is None
    b, o = run(_spec_built(acceptance_length="2.4"), _rp("deepseek_v4"))   # an acceptance length is pinned
    assert b.thinking is None and not o.subs
    plain = st.Built(deployment={"pools": [{"engine": {}}]})         # no speculation: nothing to select
    o = sc.Outcome("p", {}, {})
    sc.default_thinking(o, plain, _rp("deepseek_v4"))
    assert plain.thinking is None and not o.subs


def test_a_scored_point_replays_with_thinking_on_and_coding_and_names_it():
    tmp = Path(tempfile.mkdtemp())
    try:
        entry, env = e2e._setup(tmp, log=WITH_PARSER)
        env.field_list = _fields(acceptance_modelled=False)
        o, _ = e2e._score(tmp, entry, env, tmp / "c1")
        assert o.fidelity is not None, o.reasons
        argv = e2e._saw(env)[0]["argv"]
        assert argv[argv.index("--speculative-thinking") + 1] == "on"
        assert argv[argv.index("--speculative-fallback-category") + 1] == "coding"
        assert [s for s in o.fidelity["substitutions"] if s["subject"] == "workload.thinking_mode"]
    finally:
        shutil.rmtree(tmp)


def test_a_logged_acceptance_the_engine_models_takes_precedence_over_the_rule():
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


def test_a_server_with_no_parser_is_given_no_mode():
    tmp = Path(tempfile.mkdtemp())
    try:
        entry, env = e2e._setup(tmp, log=NO_ACCEPTANCE)
        env.field_list = _fields(acceptance_modelled=False)
        o, _ = e2e._score(tmp, entry, env, tmp / "c1")
        argv = e2e._saw(env)[0]["argv"]
        assert "--speculative-thinking" not in argv
        assert not [s for s in o.fidelity["substitutions"] if s["subject"] == "workload.thinking_mode"]
    finally:
        shutil.rmtree(tmp)
