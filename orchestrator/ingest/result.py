"""Run the simulator and read its Result document (SUB-19, DEV-8, DEV-9).

`blis run` and `blis replay` write the Result, schema version 2 (blis-substrate
contracts/spec/result), on standard output. The harness reads it there: no --metrics-path or
--results-path file, which inference-sim v0.16.0 removes. Every Result is validated with
`blis schema validate result` before a figure is read from it, so the harness holds no schema
of its own (SUB-19).

A figure is read by its identifier in the metric registry (contracts/metrics; DEV-8):
ttft_mean_ms and tpot_mean_ms are the client's mean TTFT and mean TPOT over the measured
window. Per-request figures are read from request_rows, each with its fate (DEV-9).

Every error is a ResultError whose slug names the failure in a not-scored reason
(blis_refused:<slug>). A run that exits non-zero is a RunFailed, which carries the simulator's
standard error, so the caller can name the simulator's own refusal.
"""
from __future__ import annotations

import json
import subprocess
import tempfile

SCHEMA_VERSION = 2
KIND = "Result"
TTFT_MEAN_MS = "ttft_mean_ms"
TPOT_MEAN_MS = "tpot_mean_ms"

# The measured side's definitions (DEV-8): what the InferenceX client reports as mean TTFT and
# mean TPOT (inferencex_client.summarize). Mean TTFT is the mean over requests of each request's
# time to first token; mean TPOT is the mean, over requests with two or more output tokens, of
# each request's (E2E - TTFT) / (output tokens - 1). Both over the measured window, in
# milliseconds, with requests unfinished at the horizon giving no sample. The keys are the
# fields blis-substrate contracts/metrics compares (Comparable): two figures are comparable only
# when all of them are equal.
CLIENT_DEFINITIONS = {
    TTFT_MEAN_MS: {"formula": "ttft", "statistic": "mean", "population": "requests", "window": "measured",
                   "unit": "ms", "percentile_method": None, "unfinished": "excluded"},
    TPOT_MEAN_MS: {"formula": "tpot", "statistic": "mean", "population": "requests_min_2_output_tokens",
                   "window": "measured", "unit": "ms", "percentile_method": None, "unfinished": "excluded"},
}


def check_definitions(registry: dict) -> list[str]:
    """Why the simulator's metric registry (blis_commands.metrics) cannot be compared with the
    client, or [] when it can: each metric the harness reads must exist and have the client's
    definition, field for field (DEV-8)."""
    out = []
    for metric, want in CLIENT_DEFINITIONS.items():
        d = registry.get(metric)
        if d is None:
            out.append(f"the simulator's metric registry has no {metric}")
            continue
        for k, v in want.items():
            if d.get(k) != v:
                out.append(f"the simulator's {metric} has {k} {d.get(k)!r}; the InferenceX client's has {v!r}")
    return out


class ResultError(RuntimeError):
    """The simulator refused the run, or wrote a document the harness cannot read."""

    def __init__(self, message: str, slug: str):
        super().__init__(message)
        self.slug = slug


class RunFailed(ResultError):
    """The simulator exited non-zero; stderr is its standard error."""

    def __init__(self, returncode: int, stderr: str):
        super().__init__(f"the simulator exited {returncode}: {stderr.strip()[-2000:]}", "run_failed")
        self.stderr = stderr


def _subprocess_run(argv, *, timeout, cwd):
    return subprocess.run(argv, capture_output=True, text=True, timeout=timeout, cwd=cwd)


def validate(blis: str, document: bytes, *, cwd=None, timeout: int = 600) -> None:
    """`blis schema validate result <file>`: exit 0 valid, 1 invalid (the message names each
    problem), 2 a usage error."""
    with tempfile.NamedTemporaryFile(suffix=".json") as f:
        f.write(document)
        f.flush()
        out = subprocess.run([blis, "schema", "validate", "result", f.name], capture_output=True, text=True,
                             timeout=timeout, cwd=cwd)
    if out.returncode == 1:
        raise ResultError(f"the Result does not validate: {(out.stderr or out.stdout).strip()[-2000:]}",
                          "result_invalid")
    if out.returncode != 0:
        raise ResultError(f"blis schema validate result exited {out.returncode}: {out.stderr.strip()[-2000:]}",
                          "result_validate_failed")


def parse(document: bytes) -> dict:
    """The Result as a dict, after the checks the harness's reading depends on."""
    try:
        doc = json.loads(document)
    except json.JSONDecodeError as e:
        raise ResultError(f"the simulator's standard output is not a JSON Result: {e}", "result_unreadable") from e
    if not isinstance(doc, dict) or doc.get("kind") != KIND:
        raise ResultError("the simulator's standard output is not a Result document", "result_unreadable")
    if doc.get("schema_version") != SCHEMA_VERSION:
        raise ResultError(f"Result schema_version {doc.get('schema_version')!r}; the harness reads version "
                          f"{SCHEMA_VERSION}", "result_schema_version")
    return doc


def run(argv: list[str], *, blis: str, cwd=None, timeout=None, runner=None) -> tuple[dict, bytes, str]:
    """Run one simulation, validate its Result, and return it with its bytes and the run's
    standard error. `runner(argv, timeout=, cwd=)` returns a CompletedProcess with text output:
    subprocess.run by default, or score.run_capped. subprocess.TimeoutExpired and the runner's
    own exceptions pass through."""
    proc = (runner or _subprocess_run)(argv, timeout=timeout, cwd=cwd)
    if proc.returncode != 0:
        raise RunFailed(proc.returncode, proc.stderr)
    document = proc.stdout.encode("utf-8")
    validate(blis, document, cwd=cwd)
    return parse(document), document, proc.stderr


def figure(doc: dict, metric: str) -> float:
    """A predicted figure by its registry identifier. A run that failed an acceptance condition
    of its frame reports no metrics (DEV-7), and that is an error here, never a zero."""
    m = (doc.get("metrics") or {}).get(metric)
    if not isinstance(m, dict) or not isinstance(m.get("value"), (int, float)) or isinstance(m.get("value"), bool):
        failed = [c for c in (doc.get("frame") or {}).get("acceptance") or [] if not c.get("met")]
        why = f"; frame acceptance not met: {failed}" if failed else ""
        raise ResultError(f"the Result reports no {metric}{why}", "metrics_incomplete")
    return float(m["value"])


def rows(doc: dict) -> list[dict]:
    """The Result's per-request rows. The harness asks for them, so their absence is an error."""
    r = doc.get("request_rows")
    if not isinstance(r, list):
        raise ResultError("the Result has no request_rows", "request_rows_missing")
    return r


def requests_complete(doc: dict, sent: int) -> None:
    """The measured run completed every request it sent, so the simulated one must too: a mean
    over the survivors of a run that dropped, timed out or never finished requests describes a
    different, easier point (the slowest are the ones lost). The Result counts every generated
    request's fate once, and the counts sum to generated (DEV-9), so generated and completed
    both equal to `sent` leave no request with another fate. A request that stopped at a length
    limit ran other lengths than the ones sent, so it refuses the run too."""
    q = doc.get("requests") or {}
    if q.get("generated") != sent or q.get("completed") != sent or q.get("length_capped"):
        dropped = sum((q.get("dropped") or {}).values())
        raise ResultError(f"the run completed {q.get('completed')} of {q.get('generated')} generated request(s), "
                          f"{sent} sent ({dropped} dropped, {q.get('timed_out')} timed out, "
                          f"{q.get('in_flight_at_horizon')} in flight and {q.get('queued_at_horizon')} queued at the "
                          f"horizon, {q.get('not_started')} not started, {q.get('length_capped')} length-capped)",
                          "requests_incomplete")


def engine_report(doc: dict, key: str):
    """A value from the engine's own report (reports.engine.cluster), or None."""
    return (((doc.get("reports") or {}).get("engine") or {}).get("cluster") or {}).get(key)


def kernel_report(doc: dict) -> dict | None:
    """The kernel's own report (reports.kernel), verbatim, or None when the run has none."""
    k = (doc.get("reports") or {}).get("kernel")
    return k if k else None


# Coefficient methods (design section 9.2). measured and calibrated keep a point at G1;
# not_charged is deliberately zero. The rest are G2 substitutions (design 11.3):
# transferred, literature, vendor_spec, roofline and assumed by the design's list, and
# copied (carried over from another scope, a transfer by another name).
TRUSTED_METHODS = ("measured", "calibrated", "not_charged")
SUBSTITUTED_METHODS = ("transferred", "literature", "vendor_spec", "roofline", "assumed", "copied")
REPORT_SUBJECT = "selected-entry report"


def coefficient_substitutions(doc: dict) -> list[dict]:
    """The G2 substitutions the Result's selected-entry report names (design 11.3).

    Each coefficient the run priced with is in doc["selected_entries"]["coefficients"] with its
    set, name and method. A method other than measured or calibrated is a `coefficient_method`
    substitution (subject set/name, detail the method). A Result with no selected-entry report
    (an older build) names the single substitution `coefficient_method` on the report itself, so
    no G1 is published for coefficients nobody read.

    The design's `coefficient_range` (an extrapolated or unidentified lookup) cannot be named
    yet: the Result carries no range field. When it does, it is read here."""
    report = doc.get("selected_entries")
    if not isinstance(report, dict):
        return [{"kind": "coefficient_method", "subject": REPORT_SUBJECT, "detail": "not read"}]
    out = []
    for c in report.get("coefficients") or []:
        method = c.get("method")
        if method in TRUSTED_METHODS:
            continue
        if method not in SUBSTITUTED_METHODS:
            raise ResultError(f"selected_entries: coefficient {c.get('set')}/{c.get('name')} has method "
                              f"{method!r}, not one of design 9.2's", "coefficient_method_unknown")
        out.append({"kind": "coefficient_method", "subject": f"{c['set']}/{c['name']}", "detail": method})
    return sorted(out, key=lambda s: (s["subject"], s["detail"]))


ACCEPTANCE_SUBJECT = "speculative_config.acceptance_length"


def acceptance_substitution(doc: dict) -> dict:
    """The G2 substitution for a drafter whose acceptance the run did not record (design D8):
    blis resolves it from the substrate's profile, and the Result's input.workload_properties
    says which. Kind estimated; the detail names the profile (set/key), or says the Result does
    not report it."""
    for p in (doc.get("input") or {}).get("workload_properties") or []:
        if p.get("name") == "speculative_acceptance":
            if p.get("source") == "profile" and p.get("profile"):
                detail = f"profile {p['profile']} from the registry"
            else:
                detail = f"supplied by {p.get('source')}, not a registry profile"
            return {"kind": "estimated", "subject": ACCEPTANCE_SUBJECT, "detail": detail}
    return {"kind": "estimated", "subject": ACCEPTANCE_SUBJECT, "detail": "profile not reported"}
