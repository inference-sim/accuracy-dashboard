"""Writes docs/grades.md from grade.py, so the document cannot drift from the code.

The grade names, the G5 reasons and the substitution kinds come from grade.py's tuples. The prose
for each one lives below, and a test (test_gen_grade_doc.py) fails when a tuple gains or loses a
member without its prose, and when docs/grades.md is not what this script writes.

    python3 orchestrator/ingest/gen_grade_doc.py          # write docs/grades.md
    python3 orchestrator/ingest/gen_grade_doc.py --check  # fail if the file is stale
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import assess  # noqa: E402
import grade as gr  # noqa: E402
import pd as pdm  # noqa: E402
import pd_recipe as pdr  # noqa: E402
import router_table as rtab  # noqa: E402

DOC = HERE.parent.parent / "docs" / "grades.md"

GRADE_TEXT = {
    gr.G1: "Exact. Every condition below was evaluated and is true.",
    gr.G2: "Estimated. The point is scored, with every substitution named on it. A condition that could "
           "not be evaluated is one of those substitutions.",
    gr.G3: "The run measured another release of the engine, and no function the engine ports from upstream "
           "changed between the two releases.",
    gr.G4: "As G3, but a ported function changed; or the build is nightly or custom; or the engine has not "
           "published its list of ported functions, so that cannot be told.",
    gr.G5: "Not scored, for one reason of the closed list below.",
}

G1_CONDITIONS = (
    "The run's engine release is the release the scoring simulator runs.",
    "Each library version the run used maps to the kernel hash BLIS priced (`kernel_hash`).",
    "Every field the run sets is modelled, or proven inert, and its value is in a value class the "
    "engine's evidence covers (`value_class`).",
    "Every coefficient the point used is measured or calibrated, and none was extrapolated or "
    "unidentified (`coefficient_method`, `coefficient_range`).",
    "The value the engine resolves for a field the run left unset is the value the run used "
    "(`resolved_differs`).",
    "The simulated requests are the ones the run's client sent (`client_difference`).",
)

G5_TEXT = {
    "code_not_visible": ("The engine code the build runs cannot be seen (a private image). The scorer emits no such reason today: a build it cannot resolve is G4 (nightly or custom).",
                         "Not applicable until the scorer tells a private build from a nightly one."),
    "router_unsupported": ("The run was measured behind a router BLIS does not host. BLIS hosts llm-d's router only.",
                           "Host the router in BLIS (a router in inference-sim, then the scenario names it)."),
    "topology_unsupported": ("The deployment is a shape the scenario cannot state. The subject names which part of the layout (the table below): "
                             "a prefill/decode split whose pools the stack cannot yet run, or a replay it does not yet write.",
                             "Add the topology to the engine and the deployment block, or the scenario writer; the subject says which."),
    "value_not_recorded": ("A value the simulation needs was recorded by no source: the server log is missing, the launch "
                           "artifact does not match the row, a required setting is absent, the client's scenario cannot be replayed, "
                           "or a prefill/decode run's recipe cannot be found (`recipe_unresolved`, table below).",
                           "Record the value (InferenceX uploads the log or artifact), or give the field an estimation rule in fields.json."),
    "field_not_modelled": ("The run set a field the engine's fields.json lists as not modelled, with rule `none`.",
                           "Model the field in the engine, or give it `leave_unset` or `substitute` in fields.json."),
    "field_unclassified": ("The run set a field that fields.json lists but has not classified.",
                           "Classify the field in fields.json."),
    "engine_unsupported": ("The row's inference engine is not vLLM.",
                           "Add the engine (blis-sglang, blis-trt) and its fields.json; the score then reads that engine's list."),
    "not_in_catalog": ("The model, the chip's coefficients or the speculative drafter is not in the catalog or registry the simulator reads.",
                       "Add the model or drafter to the catalog, or measure the chip's coefficients, and release them."),
    "field_not_in_release": ("The run set a field the engine release does not list.",
                             "Add the field to the release's fields.json, or score the point on a release that lists it."),
    "value_conflict": ("Two sources of one stage record different values for a field (launch configuration against the logged arguments, or a launch node size against the runners table).",
                       "Correct the source; the harness never picks one."),
    "build_unparseable": ("The run's image and log banner name no engine build at all. The scorer emits no such reason today: a build it cannot resolve is G4 (nightly or custom).",
                          "Not applicable until the scorer tells an unnamed build from a nightly one."),
}

KIND_TEXT = {
    "coefficient_method": "A coefficient the point used is transferred, literature, vendor_spec, roofline, assumed or copied, not measured or calibrated.",
    "coefficient_range": "A coefficient lookup was extrapolated or unidentified.",
    "execution_mode": "The point ran in a substituted execution mode.",
    "kernel_hash": "A library's kernel hash differs from the one BLIS priced. When the condition could not be decided it is named by kind `unevaluated`, not this one.",
    "value_class": "A modelled field's value is outside the value classes its evidence covers.",
    "estimated": "A field's value was estimated by the engine's rule (`leave_unset` or `substitute`), or a needed value the run did not record was taken by that rule; or a prefill/decode pool's engine arguments are the run's recipe's (subject `engine.<pool>.recipe`), or a speculative run's thinking mode is the reasoning-parser rule's (subject `workload.thinking_mode`).",
    "interim_status": "The run set a field whose status is `inert_unproven`, allowed only during a release plan.",
    "resolved_differs": "The value the engine resolves differs from the one the run used.",
    "client_difference": "The simulated requests differ from the ones the run's client sent.",
    "router_differs": "The run's router, which BLIS does not host, was replaced by an llm-d router policy from the substrate's router table. The subject is the router the run used; the point names the table entry, the policy (one llm-d offers), the router build (a full commit the entry lists), the table's evidence, and the entry's difference statements and bound as it states them.",
    "unevaluated": "A condition of G1 could not be evaluated because the data it needs is not recorded for the point. The subject is the condition, named by the kind that would record its failure.",
    "later_record": "A fact of the cluster the run's own record lacks was taken from the benchmark's later record of the same runner.",
}
TOPOLOGY_SUBJECT_TEXT = {
    pdm.POOL_DP: ("A prefill or decode pool runs data-parallel attention (data-parallel size above 1).",
                  "The engine refuses a KV transfer with data parallelism: blis-vllm#47 (M3)."),
    pdm.UNEQUAL_DP: ("The two pools differ in data-parallel size (a DEP prefill pool with a TEP decode pool, or the reverse).",
                     "The placement refuses pools of different data-parallel size: inference-sim#1952 (M3)."),
    pdm.NOT_RECORDED: ("The row records a pool with no workers or no GPUs.", "Not removable: the row does not describe a prefill/decode run."),
    pdm.AGENTIC: ("An agentic replay of a prefill/decode deployment is not written.",
                  "Write the agentic replay for two pools, with the router's session affinity (accuracy-dashboard#64, M3)."),
}
RECIPE_SLUG_TEXT = {
    pdr.NO_MASTER: "No search-space item of the master configuration at the run's commit is this row (framework, model, runner, precision, sequence lengths, concurrency, workers, parallel sizes, speculation).",
    pdr.AMBIGUOUS: "More than one item fits the row with different recipes, or the launch scripts' overlays give different files.",
    pdr.NOT_IN_TREE: "The recipe the item names is in no file of InferenceX at the run's commit: it came from the srt-slurm repository's own, unpinned branch.",
    pdr.UNREADABLE: "The recipe file does not parse as a recipe.",
    pdr.NO_CONFIG_FILE: "The item names no recipe (`CONFIG_FILE`).",
    pdr.NO_COMMIT: "The run's commit, or its tree, cannot be read (a run of another repository, or a commit the repository no longer holds).",
}
ROUTER_OUTCOME_TEXT = {
    rtab.NO_ENTRY: "No entry of the router table has the run's router, mode and session-affinity setting.",
    rtab.NO_POLICY: "The entry says no llm-d policy is close enough.",
    rtab.REVISION_NOT_COVERED: "The entry does not list the run's router build, or the run records none (a wheel version maps to no commit).",
    rtab.NO_BOUND: "The entry maps, and no ratio of its bound has a regime that holds the point (its request lengths, concurrency, catalog model, hardware part and pool shape).",
}
G34_TEXT = {
    "other_release": "The run measured another engine release than the simulator runs.",
    "changed_functions": "A function the engine ports changed between the two releases.",
    "nightly_or_custom": "The build is a nightly, a dev build, a fork or a private image.",
    "ported_functions_unpublished": "The engine has not published its list of ported functions or the diff.",
}
RUN_FAULT_TEXT = {
    "blis_refused": "The simulator refused a scenario the harness wrote from recorded values. A refusal for memory or time (`insufficient_memory`, `timeout`) lists the point as failed. Any other refusal stops the run.",
    "setting_differs": "The scenario written lost a value the run recorded. The run stops.",
}


def render() -> str:
    L = ["# Closeness grades", "",
         "Generated by `orchestrator/ingest/gen_grade_doc.py` from `orchestrator/ingest/grade.py`; do not edit by hand. "
         "Design §11.3 and §11.4 define the grades. Every point gets one grade: the highest-numbered grade whose conditions apply.", "",
         "## The grades", "", "| Grade | Meaning |", "|---|---|"]
    L += [f"| {g} | {GRADE_TEXT[g]} |" for g in gr.GRADES]
    L += ["", "A point counts toward the headline when its grade is G1 to G4. Each grade is also reported on its own: "
          "its share of the points, and its own accuracy. A figure over fewer than 10 points is shown as `too few points`.", "",
          "## G1: the conditions", ""]
    L += [f"{i}. {c}" for i, c in enumerate(G1_CONDITIONS, 1)]
    L += ["", "## Unevaluated conditions", "",
          "A condition is *unevaluated* when no source records the datum it needs. An unevaluated condition is not assumed true: "
          "the point names it as a substitution of kind `" + gr.NOT_CHECKED_KIND + "` whose subject is the condition, so the point is G2 at best. "
          "A point can be G1 only when none of these is named.", "",
          "| Condition | Meaning |", "|---|---|"]
    L += [f"| `{k}` | {KIND_TEXT[k]} |" for k in gr.UNCHECKED_KINDS]
    L += ["", "A condition leaves this table when it is evaluated from data; the point then names a substitution of that kind only when it is true of the point.", "",
          "## Substitutions (G2)", "", "| Kind | Meaning |", "|---|---|"]
    L += [f"| `{k}` | {KIND_TEXT[k]} |" for k in gr.G2_KINDS]
    L += ["", "## Other release or build (G3, G4)", "", "| Kind | Meaning |", "|---|---|"]
    L += [f"| `{k}` | {G34_TEXT[k]} |" for k in gr.G34_KINDS]
    L += ["", "## G5: not scored", "",
          "The list is closed (design §11.4). The scorer's own reason codes map onto it (`assess.G5_FOR_REASON`); a reason with no place here is an error.", "",
          "| Reason | Meaning | How it is removed |", "|---|---|---|"]
    L += [f"| `{c}` | {G5_TEXT[c][0]} | {G5_TEXT[c][1]} |" for c in gr.G5_CODES]
    L += ["", "### Named `topology_unsupported` subjects (prefill/decode)", "", "| Subject | Meaning | Removed by |", "|---|---|---|"]
    L += [f"| `{k}` | {v[0]} | {v[1]} |" for k, v in TOPOLOGY_SUBJECT_TEXT.items()]
    L += ["", "### Named `recipe_unresolved` subjects", "", "| Subject | Meaning |", "|---|---|"]
    L += [f"| `{k}` | {RECIPE_SLUG_TEXT[k]} |" for k in pdr.SLUGS]
    L += ["", "### Named `router_unsupported` subjects (`<router>:<outcome>`)", "", "| Outcome | Meaning |", "|---|---|"]
    L += [f"| `{k}` | {ROUTER_OUTCOME_TEXT[k]} |" for k in rtab.OUTCOMES if k != rtab.MAPPED]
    L += ["", "The scorer's reasons and the G5 reason each becomes:", "", "| Scorer reason | G5 reason |", "|---|---|"]
    L += [f"| `{k}` | `{v}` |" for k, v in assess.G5_FOR_REASON.items()]
    L += ["", "## Run faults (not a grade)", "",
          "A point whose scoring fails has no grade. It is listed as failed, and the run stops unless every fault is a runner limit.", "",
          "| Fault | Meaning |", "|---|---|"]
    L += [f"| `{k}` | {RUN_FAULT_TEXT[k]} |" for k in assess.RUN_FAULTS]
    L += ["", "## Reading the tables", "",
          "- A comparison table (`orchestrator/baseline/compare.py`) is labelled in-sample or held-out. In-sample means no anchor list exists, so no point is held out. A table never mixes the two.",
          "- *Blocks* counts the points a G5 reason or substitution holds back. *Alone* counts the points whose only reason it is, so fixing it alone would score them. *Demotes* counts the graded points a substitution holds below G1 (design §11.6).",
          "- AMD (mi300x, mi325x, mi355x) and TPU points are out of scope for M2 to M4. The comparison tables count them apart from the in-scope points; the scorer's reason codes are unchanged.", ""]
    return "\n".join(L)


def main(argv=None) -> int:
    check = "--check" in (argv if argv is not None else sys.argv[1:])
    text = render()
    if check:
        if not DOC.is_file() or DOC.read_text() != text:
            print(f"{DOC} is stale; run gen_grade_doc.py", file=sys.stderr)
            return 1
        return 0
    DOC.write_text(text)
    print(f"wrote {DOC}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
