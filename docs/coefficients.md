# How the cost model's coefficients are produced and graded

The dashboard consumes coefficients; it does not produce them. The cost model's constants live in the substrate's **registry**, and the methodology of that registry is the substrate's to state. This page says only what the dashboard relies on and links to the pages that define it, at the pinned substrate commit `0182c0ef42b08ef5a0b196b3e413c21c16b6d28d` (the pin is a parameter of the after-run; the links move with it).

| Question | Substrate page |
|---|---|
| What is a coefficient, its entry, its scope and sets | [Coefficients (concepts)](https://github.com/inference-sim/blis-substrate/blob/0182c0ef42b08ef5a0b196b3e413c21c16b6d28d/docs/registry/concepts/coefficients.md) |
| What a **method** is (measured, calibrated, transferred, literature, vendor_spec, roofline, assumed, copied, not_charged) and how a value was obtained | the same page, *Method: how the value was obtained* |
| Where the numbers come from; why a sweep can fit a constant and a forward pass cannot | [Evidence](https://github.com/inference-sim/blis-substrate/blob/0182c0ef42b08ef5a0b196b3e413c21c16b6d28d/docs/registry/concepts/evidence.md) |
| How a coefficient is defined, fitted and checked; the lane rule; train, validate, evaluate; per-part provenance | [Methodology](https://github.com/inference-sim/blis-substrate/blob/0182c0ef42b08ef5a0b196b3e413c21c16b6d28d/docs/registry/methodology.md) |
| Fitting principles: data roles, the loss, where direct data is missing | [Fitting principles](https://github.com/inference-sim/blis-substrate/blob/0182c0ef42b08ef5a0b196b3e413c21c16b6d28d/docs/registry/fitting-principles.md) |
| Choosing between the kernel's two step-time band edges | [Band selection](https://github.com/inference-sim/blis-substrate/blob/0182c0ef42b08ef5a0b196b3e413c21c16b6d28d/docs/registry/band-selection.md) |
| Re-deriving every value from the original datasets | [Reproducing coefficients](https://github.com/inference-sim/blis-substrate/blob/0182c0ef42b08ef5a0b196b3e413c21c16b6d28d/docs/registry/reproducing-coefficients.md) |
| What the Result carries about the coefficients a run used | [Result](https://github.com/inference-sim/blis-substrate/blob/0182c0ef42b08ef5a0b196b3e413c21c16b6d28d/docs/contracts/reference/result.md), `selected_entries` |
| The point record the dashboard writes | [Point record](https://github.com/inference-sim/blis-substrate/blob/0182c0ef42b08ef5a0b196b3e413c21c16b6d28d/docs/contracts/reference/point-record.md) |

## What the dashboard reads about a coefficient

For each coefficient a simulation priced with, the Result's `selected_entries` names the set, the name, the method, the scope and the file, and (with `closeness_version` 1 or 2) the kernel implementations the entry is valid for (and, with 2, the ones priced and whether the entry matched exactly), its fit range and interval, and whether the run left the range or the entry is unidentified. The dashboard grades:

- a method other than *measured*, *calibrated* or *not_charged* as a G2 `coefficient_method` substitution, named by `set/name`;
- an extrapolated or unidentified lookup as a `coefficient_range` substitution, where the entry states what the flag needs;
- a library version whose kernel hash differs from the one priced (the entry's `priced` list) as a `kernel_hash` substitution (not evaluable today); a condition that could not be decided as an `unevaluated` substitution naming it.

See [closeness grades](closeness-grades.md). The method *error* and the registry's own ranking of coefficient quality (VAL) belong to the registry's methodology above; the dashboard does not recompute them.

## The learned or analytical estimator

A learned or analytical estimator of residual terms is planned. When it exists, its fits may use only the train split of the development split ([protocol](m2/evaluation-protocol.md)): the registry's fitters read the published series list and a check fails if an entry cites a validation or test row. Its methodology page belongs in the registry; this page will link to it and will not copy it.
