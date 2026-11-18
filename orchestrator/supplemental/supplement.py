#!/usr/bin/env python3
"""derived-213.json (reconstruct.py derive) -> supplemental-recipes.json, the file the dashboard's supplemental-recipe loader reads:
one entry per unit whose own recipe is gone, with the launch in the srt launch-config form settings.read_launch_config reads
(roles.aggregated.args in CLI spelling, roles.aggregated.env, model.path, resources.gpus_per_node)."""
import json, os, sys
HERE = os.environ.get("OUT", os.path.dirname(os.path.abspath(__file__)))
IMAGE = "vllm/vllm-openai:v0.10.2"
# the runner launch scripts' `-e` variables the benchmark script does not set (runners/launch_b200-nvd.sh, launch_h100-cr.sh at the commit)
# NOT stated: a surviving run's server log does not show them either, so the scorer never sees them for a run with a log; the
# omission is named on the point (OMITTED_RUNNER_ENV).
RUNNER_ENV = {}
OMITTED_RUNNER_ENV = {"b200": ["NCCL_GRAPH_REGISTER=0", "TORCH_CUDA_ARCH_LIST=10.0"], "h100": ["TORCH_CUDA_ARCH_LIST=9.0"], "h200": []}
SUBSTITUTION = ("recipe reconstructed from InferenceX scripts at {commit}; the run's own recipe is gone; "
                "vLLM v0.10.2 modelled as 0.33.0")
NOT_FLAGS = {"host", "port", "model"}

def flags_of(args):
    out = {}
    for k, v in args.items():
        if k in NOT_FLAGS: continue
        name = k.replace("_", "-")
        if v is False:
            out["no-" + name] = True
        else:
            out[name] = v
    return out

def launch_flags(a, o):
    f = flags_of(a)
    # the benchmark scripts pass --disable-log-requests (a v0.10.2 argument): stated as the run's launch, translated by the scorer
    f["disable-log-requests"] = True
    # --tensor-parallel-size is the only size they pass; vLLM's defaults for the others are 1, and the engine's GPUs are TP x 1 x 1
    f.setdefault("pipeline-parallel-size", 1)
    f.setdefault("data-parallel-size", 1)
    return f

def main():
    d = json.load(open(f"{HERE}/derived-213.json"))
    units = {}
    for o in d:
        v = o["variants"][0]
        a = v["args"]
        env = dict(v.get("env") or {}); env.update(RUNNER_ENV.get(o["hardware"], {}))
        launch = {"roles": {"aggregated": {"args": launch_flags(a, o), "env": env}}, "model": {"path": a["model"]}, "resources": {"gpus_per_node": 8}}
        units[o["unit"]] = {"launch": launch, "commit": o["commit"], "script": v["script"], "image": IMAGE,
                            "alternative_scripts": [x["script"] for x in o["variants"][1:]],
                            "substitution": SUBSTITUTION.format(commit=o["commit"]),
                            "defaults_stated": ["pipeline-parallel-size=1", "data-parallel-size=1"],
                            "runner_env_omitted": OMITTED_RUNNER_ENV.get(o["hardware"], []),
                            "split": o["split"], "hardware": o["hardware"], "precision": o["precision"]}
    json.dump({"about": "Launches reconstructed from InferenceX's benchmark scripts for matched units whose own recipe is gone (HTTP 404). "
                        "Validated on gpt-oss-120b vLLM units of 2026 whose server logs survive; no surviving Llama-3.3 October-2025 log exists to check against.",
               "units": units}, open(f"{HERE}/supplemental-recipes.json", "w"), indent=1, sort_keys=True)
    print(len(units))

if __name__ == "__main__":
    main()
