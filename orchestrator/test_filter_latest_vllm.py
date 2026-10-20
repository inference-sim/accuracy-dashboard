"""Unit tests for the latest-N vLLM corpus filter (RFC discussion #2, point 2).

Run: python3 -m pytest orchestrator/test_filter_latest_vllm.py
 or: python3 orchestrator/test_filter_latest_vllm.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
import filter_latest_vllm as flv  # noqa: E402


def _sweep(image, model="m", gpu="b200", wl="1k:1k", tp=8, stated=None, pts=1):
    return {
        "model": model, "gpu": gpu, "precision": "fp4", "framework": "vllm",
        "serving": "aggregated", "spec_method": "none", "workload": wl,
        "parallelism": {"tp_size": tp}, "stated_config": stated or {"block_size": 256},
        "image": image, "label": "L",
        "points": [{"concurrency": c} for c in range(pts)],
    }


def test_is_numbered():
    assert flv._is_numbered("0.25.1")
    assert flv._is_numbered("0.21")
    assert not flv._is_numbered("nightly")
    assert not flv._is_numbered("deepseekv4-cu130")
    assert not flv._is_numbered(None)


def test_latest_n_window_is_newest_numbered_in_dump():
    # six numbered versions present; N=5 keeps the newest five, drops 0.20.0
    sweeps = [_sweep(f"vllm/vllm-openai:v{v}") for v in
              ["0.25.1", "0.25.0", "0.24.0", "0.22.0", "0.21.0", "0.20.0"]]
    kept, rep = flv.filter_sweeps(sweeps, n=5)
    assert rep["window_kept"] == ["0.25.1", "0.25.0", "0.24.0", "0.22.0", "0.21.0"]
    assert "0.20.0" not in rep["window_kept"]
    # each sweep is a distinct version → distinct identity? no: identical identity except version,
    # so dedup-to-latest collapses them to ONE (the newest, 0.25.1).
    assert len(kept) == 1
    assert flv._parse_vllm_version(kept[0]["image"]) == "0.25.1"


def test_unnumbered_builds_excluded():
    sweeps = [
        _sweep("vllm/vllm-openai:v0.25.1"),
        _sweep("vllm/vllm-openai:nightly-abc123"),
        _sweep("vllm/vllm-openai:deepseekv4-cu130"),
    ]
    kept, rep = flv.filter_sweeps(sweeps, n=5)
    assert "nightly" in rep["excluded_unnumbered"]
    assert "deepseekv4-cu130" in rep["excluded_unnumbered"]
    # only the numbered one survives
    assert len(kept) == 1
    assert flv._parse_vllm_version(kept[0]["image"]) == "0.25.1"


def test_dedup_keeps_newest_version_per_identity():
    # two DIFFERENT identities (different gpu), each measured on two versions.
    sweeps = [
        _sweep("vllm/vllm-openai:v0.21.0", gpu="b200"),
        _sweep("vllm/vllm-openai:v0.25.0", gpu="b200"),  # newer, same identity → wins
        _sweep("vllm/vllm-openai:v0.22.0", gpu="h100"),
        _sweep("vllm/vllm-openai:v0.24.0", gpu="h100"),  # newer, same identity → wins
    ]
    kept, rep = flv.filter_sweeps(sweeps, n=5)
    assert len(kept) == 2  # one per identity
    by_gpu = {k["gpu"]: flv._parse_vllm_version(k["image"]) for k in kept}
    assert by_gpu == {"b200": "0.25.0", "h100": "0.24.0"}


def test_different_stated_config_not_deduped():
    # same model/gpu/version but DIFFERENT stated_config → different BLIS inputs → both kept
    sweeps = [
        _sweep("vllm/vllm-openai:v0.25.0", stated={"block_size": 256}),
        _sweep("vllm/vllm-openai:v0.25.0", stated={"block_size": 128}),
    ]
    kept, _ = flv.filter_sweeps(sweeps, n=5)
    assert len(kept) == 2


def test_model_path_only_difference_is_deduped():
    # stated_config.model is a load path/alias — same model from a different location. BLIS predicts
    # identically, so sweeps differing ONLY in it must collapse to one (not look-alike duplicate rows).
    sweeps = [
        _sweep("vllm/vllm-openai:v0.25.0", stated={"model": "nvidia/Foo-NVFP4", "block_size": 256}),
        _sweep("vllm/vllm-openai:v0.25.0", stated={"model": "/scratch/models/Foo-NVFP4", "block_size": 256}),
    ]
    kept, _ = flv.filter_sweeps(sweeps, n=5)
    assert len(kept) == 1  # collapsed — model path is not a BLIS input


def test_points_preserved_on_kept_sweeps():
    sweeps = [_sweep("vllm/vllm-openai:v0.25.1", pts=5)]
    kept, _ = flv.filter_sweeps(sweeps, n=5)
    assert len(kept[0]["points"]) == 5  # a kept sweep keeps ALL its concurrency points


def test_empty_when_no_numbered_versions():
    sweeps = [_sweep("vllm/vllm-openai:nightly-x"), _sweep("vllm/vllm-openai:custombuild")]
    kept, rep = flv.filter_sweeps(sweeps, n=5)
    assert kept == []
    assert rep["window_kept"] == []


if __name__ == "__main__":
    import traceback
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL {fn.__name__}")
            traceback.print_exc()
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
