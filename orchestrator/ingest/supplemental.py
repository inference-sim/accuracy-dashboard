"""Reconstructed launches for matched units whose own recipe is gone.

A matched InferenceX unit whose workflow run and server log answer HTTP 404 (pull-errors.json) has no recipe the
scorer can read. For a unit of a sweep whose benchmark scripts are still in the InferenceX repository, the launch
the script gives (what `vllm serve` is handed, config.yaml, the variables in force) can be recovered by running
the script with the environment the workflow gave it (M3.1/dspark/recipe/reconstruct.py; the file it writes is
supplemental-recipes.json). That launch is not the run's record: it is read as the launch config and named on
the point, the run's own release is the script's image tag, and the grade is no higher than G4.
"""
from __future__ import annotations

import json
from pathlib import Path


def load(path: Path) -> dict[str, dict]:
    """unit id -> its reconstructed launch, from supplemental-recipes.json."""
    d = json.loads(Path(path).read_text())
    return d["units"]


def release_of(image: str) -> str:
    """The vLLM release an image tag names: vllm/vllm-openai:v0.10.2 -> 0.10.2."""
    return image.rsplit(":", 1)[-1].lstrip("v")


def entry_for(unit: dict) -> dict:
    """The point's supplemental_recipe: the launch, the release and the substitution text."""
    return {"launch": unit["launch"], "release": release_of(unit["image"]), "commit": unit["commit"],
            "script": unit["script"], "text": unit["substitution"], "image": unit["image"],
            "defaults": unit.get("defaults_stated") or [], "runner_env_omitted": unit.get("runner_env_omitted") or []}


def substitution(supp: dict) -> dict:
    d = f"{supp['text']} (script {supp['script']}, image {supp['image']})"
    if supp.get("defaults"):
        d += f"; sizes the script leaves at vLLM's default, stated: {', '.join(supp['defaults'])}"
    if supp.get("runner_env_omitted"):
        d += (f"; the runner's own environment is not stated ({', '.join(supp['runner_env_omitted'])}): no server log shows it, "
              f"so a run with a log does not state it either")
    return {"kind": "estimated", "subject": "engine.recipe", "detail": d}


# ----------------------------------------------------------------------------------------------- the points

import re

_HTTP = re.compile(r"HTTP(?:Error)?[ :]+(\d{3})")
GONE = ("404", "410")


def is_gone(error: str) -> bool:
    """A pull error that says the record no longer exists: HTTP 404 or 410, as baseline/matched.py's pull_error_reason."""
    m = _HTTP.search(error or "")
    return bool(m and m.group(1) in GONE)


def points(units: dict[str, dict], sources: Path) -> tuple[list[dict], dict[str, str]]:
    """(manifest points, {unit: why not}) for the supplemental units.

    `sources` is the matched pull's directory: match.json (unit -> records), dump-rows.jsonl (the InferenceX rows) and
    pull-errors.json (unit -> the error that kept its record out of the pull). A unit becomes a point only when its pull error
    says the record is gone (404 or 410): a unit whose own recipe survives is never given a reconstructed one, and a unit
    the pull failed to read for another reason is left to be pulled again. The point carries no file and the reconstructed
    launch as `supplemental_recipe`; its identity is the ledger's, and must hash to the unit id."""
    import contract as ct
    sources = Path(sources)
    errors = json.loads((sources / "pull-errors.json").read_text())
    matched = {p["unit"]: p for p in json.loads((sources / "match.json").read_text())["points"]}
    dump = {}
    for line in (sources / "dump-rows.jsonl").read_text().splitlines():
        r = json.loads(line)
        dump[str(r["id"])] = r
    dates = ct.run_dates(list(dump.values()))
    pts, skipped = [], {}
    for unit, u in sorted(units.items()):
        if unit not in errors:
            skipped[unit] = "the pull holds the unit's own record"
        elif not is_gone(errors[unit]):
            skipped[unit] = f"the pull error is not a gone record ({errors[unit]})"
        elif unit not in matched:
            skipped[unit] = "the unit is not in match.json"
        else:
            rec = str(matched[unit]["records"][0])
            row = dump[rec]
            ident = ct.unit_identity(row, dates)
            if ct.point_id(ident) != unit:
                skipped[unit] = "the unit's identity does not hash to its id"
                continue
            supp = entry_for(u)
            pts.append({"point_id": unit, "records": [rec], "row": row, "files": {}, "reasons": [], "identity": ident,
                        "build": {"image": u["image"], "ref": "v" + supp["release"], "source": "supplemental", "match": "reconstructed"},
                        "measurements": [{"metrics": row["metrics"], "record": rec}], "client_args": None,
                        "client_args_reason": "job_log_expired", "client_commit": None, "result_filename": None,
                        "artifact_notes": ["artifact_unmatched:no_recipe_fingerprint"], "supplemental_recipe": supp})
    return pts, skipped
