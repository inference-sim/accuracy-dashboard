"""A refusal the engine words with a quoted scenario name is named, not cut to "scenario"; Gemma 4's unequal KV page sizes are
a named G5 gap of the engine; a configiq row recording fewer requests than its concurrency is refused by name (value_conflict).

Run: python3 -m pytest orchestrator/ingest/test_named_scenario_refusals.py"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import assess as asx  # noqa: E402
import score as sc  # noqa: E402
import test_configiq_score as tcs  # noqa: E402

KV = ('time="2026-11-17T23:12:15-05:00" level=fatal msg="scenario \\"cq-04353280edecc7b4.yaml\\": engine vllm 0.33.0: vllmengine: '
      'cq-04353280edecc7b4.yaml: vllm: kv_layers: kv: KV layers of unequal page sizes (8192 and 4096 elements per token) need '
      'vLLM\'s packed KV cache groups of several block sizes, which are not modelled"\n')
OTHER = 'level=fatal msg="scenario \\"p-0123456789abcdef.yaml\\": the kernel will not price a layer of this kind"\n'


def test_a_refusal_with_a_quoted_scenario_name_is_not_cut_to_the_bare_slug(tmp_path):
    slug = sc._blis_refusal(OTHER, tmp_path)
    assert slug != "blis_refused:scenario"
    assert slug.startswith("blis_refused:scenario_") and "the_kernel_will_not_price" in slug and "p-0123456789abcdef" not in slug
    # the file name is normalised, so the reason is the same for every scenario
    assert sc._blis_refusal(OTHER.replace("p-0123456789abcdef", "p-fedcba9876543210"), tmp_path) == slug
    assert sc._blis_refusal(KV, tmp_path) == sc._blis_refusal(KV.replace("04353280edecc7b4", "ffffffffffffffff"), tmp_path)


def test_a_message_without_quoted_names_reads_as_before(tmp_path):
    assert sc._blis_refusal('level=fatal msg="deployment states no max_num_seqs"\n', tmp_path) == "blis_refused:deployment_states_no_max_num_seqs"


def test_unequal_kv_page_sizes_are_a_named_gap_of_the_engine(tmp_path):
    reason = sc.value_refusal(KV, tmp_path, None)
    assert reason == "engine_unsupported:kv_unequal_page_sizes"
    assert asx.g5_of(reason) == {"code": "engine_unsupported", "subject": "kv_unequal_page_sizes"}
    assert sc.value_refusal(OTHER, tmp_path, None) is None or not sc.value_refusal(OTHER, tmp_path, None).startswith("engine_unsupported:kv")


def test_a_configiq_row_with_fewer_requests_than_its_concurrency_is_refused_by_name(tmp_path):
    rows = {f"{tcs.F}:0": tcs.prow(successful_requests=161.0, concurrency=300.0)}
    pts, outs, env = tcs.run(tmp_path, rows)
    (o,) = outs
    assert o.status == "refused" and not tcs.replays(env), (o.status, o.g5, o.faults)
    assert {"code": "value_conflict", "subject": "stated concurrency exceeds recorded requests: concurrency 300, 161 requests"} in o.g5


def test_a_configiq_row_with_as_many_requests_as_its_concurrency_is_simulated(tmp_path):
    rows = {f"{tcs.F}:0": tcs.prow(successful_requests=300.0, concurrency=300.0)}
    pts, outs, env = tcs.run(tmp_path, rows)
    (o,) = outs
    assert o.status == "scored", (o.g5, o.faults)
