#!/usr/bin/env python3
"""Score Red Hat's configiq points by simulation (configiq_score.py), with the same pins and checks as `cli.py score`.

  score_configiq.py --ledger LEDGER --rows EXPORT.jsonl --data-dir DIR --blis BLIS --catalog CAT --registry REG
                    --fields FILE --catalog-release PIN --registry-release PIN --harness-commit SHA --out DIR
                    [--sim-build TAG|SHA] [--stack FILE] [--work DIR] [--workers N] [--timeout S] [--only UNIT ...]
                    [--ledger-yaml FILE] [--withhold-split NAME ...]

LEDGER is blis-substrate's catalog/ledger (units/configiq.jsonl.gz, reports/configiq.yaml, sources.yaml). EXPORT.jsonl
is what blis-substrate's ledger/configiq/export.py prints from the downloaded dataset files, which DIR holds; they are
checked against the ledger's pinned hashes. The simulator build, the catalog, the registry and the engine's field list
are checked as `cli.py score` checks them. No network. Writes OUT/configiq-points.jsonl (every unit: scored, refused by
name, failed or withheld), OUT/points.csv (the scored points, in the InferenceX contract's columns) and OUT/summary.json.

configiq is anchor-only (design D9; plan Terms and 3C): the units scored are every ledger unit less rules.configiq.left_out of
--ledger-yaml (the units the D2 join found read under a training role), never read from anchor.yaml, and none is withheld
as a test split. --withhold-split is an opt-in for a local experiment; the nightly never sets it. The command is
a separate entry point from cli.py on purpose: cli.py's import closure is the scorer a committed InferenceX contract
names (orchestrator/baseline/test_contracts_current.py), and this source's scoring does not change those figures.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(1, str(HERE.parent))
import blis_commands as bc  # noqa: E402
import cli  # noqa: E402
import configiq as cq  # noqa: E402
import configiq_score as cqs  # noqa: E402
import fields as fl  # noqa: E402
import stack as sk  # noqa: E402
sys.path.insert(2, str(HERE.parent / "baseline"))
import sources as src  # noqa: E402
import support as sp  # noqa: E402


def run(a) -> int:
    blis = Path(a.blis).resolve()
    bad = cli.check_blis_inputs(blis, a.catalog_release, a.registry_release, a.sim_build)
    bad += cli.check_harness_commit(a.harness_commit)
    if not bad:
        bad += cli.check_metric_definitions(blis)
    field_list = fields_sha = engine_release = None
    try:
        stack = cli.read_stack(blis, a.stack)
        engine_release = stack.engine("vllm")
        field_list, fields_sha = cli.read_fields(Path(a.fields), engine_release)
    except (sk.StackError, fl.FieldsError, bc.CommandError, OSError, ValueError) as e:
        bad.append(str(e))
    if bad:
        for b in bad:
            cli._log(f"FATAL: {b}")
        return 2
    sim = blis.parent
    catalog, registry = Path(a.catalog).resolve(), Path(a.registry).resolve()
    try:
        lg, points = cqs.load_points(a.ledger, a.data_dir, a.rows, catalog)
    except (cq.ConfigiqError, OSError, ValueError) as e:
        cli._log(f"FATAL: {e}")
        return 2
    if a.ledger_yaml:
        try:
            keep = set(src.configiq_anchor_ids([p.unit_id for p in points], src.read_ledger_yaml(a.ledger_yaml)))
        except (src.SourcesError, OSError, ValueError) as e:
            cli._log(f"FATAL: {e}")
            return 2
        points = [p for p in points if p.unit_id in keep]
    if a.only is not None:
        points = [p for p in points if any(p.unit_id.startswith(x) for x in a.only)]
    release = cli._git(sim, "describe", "--tags", "--exact-match") or "unknown"
    env = cqs.Env(blis=str(blis), catalog=catalog, registry=registry, catalog_release=a.catalog_release,
                  registry_release=a.registry_release, engine_release=engine_release, sim_build=a.sim_build or release,
                  harness_commit=a.harness_commit, field_list=field_list, timeout_s=a.timeout,
                  withhold_splits=tuple(a.withhold_split or ()))
    env.catalog_obj = sp.Catalog(blis=str(blis), root=catalog)
    env.parts = sp.registry_parts(registry)
    work = Path(a.work or Path(a.out).parent / (Path(a.out).name + "-work"))
    work.mkdir(parents=True, exist_ok=True)
    try:
        outcomes = cqs.score_all(points, env, work, workers=a.workers, log=cli._log)
    except bc.CommandError as e:
        cli._log(f"FATAL: {e}")
        return 2
    d = cqs.dev_split
    prov = {"simulator": env.simulator(), "engine": {"kind": "vllm", "version": engine_release},
            "blis": {"release": release, "commit_sha": cli._git(sim, "rev-parse", "HEAD"), "catalog": a.catalog_release,
                     "registry": a.registry_release},
            "harness_commit": a.harness_commit, "fields_sha256": fields_sha,
            "dataset": {"name": "redhat-performance/configiq-performance-upstream-data", "revision": lg.revision,
                        "assets": lg.assets, "license": "CC-BY-4.0"},
            "split": {"name": "none (anchor-only, D9)", "label_only": "development", "salt": d.SALT,
                      "series": "role key (every identifying field but the concurrency)",
                      "withheld": sorted(a.withhold_split or [])},
            "experimental": not all(cli._DATA_PIN.match(x) for x in (env.sim_build, a.catalog_release, a.registry_release))}
    doc = cqs.write_outputs(Path(a.out), outcomes, prov)
    for p in doc["problems"]:
        cli._log(f"INVALID: {p}")
    c = doc["coverage"]
    cli._log(f"score-configiq: {c['scored']} scored, {c['refused']} refused, {c['failed']} failed, "
             f"{c['withheld']} withheld of {c['points']} -> {a.out}")
    return 1 if doc["problems"] else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    ap.add_argument("--ledger", required=True, help="blis-substrate's catalog/ledger")
    ap.add_argument("--rows", required=True, help="the JSON lines ledger/configiq/export.py prints from the dataset files")
    ap.add_argument("--data-dir", required=True, help="the downloaded dataset files (checked against the ledger's pins)")
    ap.add_argument("--blis", required=True, help="the blis binary (see cli.py score --blis)")
    ap.add_argument("--catalog", required=True)
    ap.add_argument("--registry", required=True)
    ap.add_argument("--catalog-release", required=True)
    ap.add_argument("--registry-release", required=True)
    ap.add_argument("--fields", required=True, help="the engine's fields.json (see cli.py score --fields)")
    ap.add_argument("--stack", help="see cli.py score --stack")
    ap.add_argument("--sim-build", help="the simulator build: a release tag or a 40-hex commit")
    ap.add_argument("--harness-commit", required=True, help="the full 40-hex commit of this checkout (X8)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--work")
    ap.add_argument("--timeout", type=int, default=3600)
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--ledger-yaml", help="a ledger.yaml: its rules.configiq.left_out units are not scored (D2 join)")
    ap.add_argument("--withhold-split", action="append", choices=("train", "validation", "test"),
                    help="local experiment only: withhold this development split (D9 withholds none)")
    ap.add_argument("--only", nargs="*", help="score only the units whose id starts with one of these")
    return run(ap.parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
