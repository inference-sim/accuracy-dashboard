/**
 * Apply the UI filters to the flat points before aggregation + regrouping. Because every
 * aggregate is recomputed from the surviving points (RFC §4.4/B3), filtering here is the only
 * place a point is hidden — nothing downstream reads a stored parent number.
 *
 * Default view is on-target vLLM (§6.3): the default state IS the headline, so it must not
 * pool off-version measurements. Multi-node is hidden by default. The tier switch is applied
 * at aggregation time (a point carries its own tier), not here, so both tiers stay available.
 */
import type { FlatPoint } from './aggregate'
import type { RouteState } from './route'

export interface FilterResult {
  points: FlatPoint[]
  /** True when the on-target default was requested but the dump has NO on-target points, so we
   *  fell back to all versions (RFC §6 open-question 2: a freshness fallback rather than a hard
   *  on-target-only headline that would show an empty dashboard). The UI surfaces this. */
  onTargetFellBack: boolean
}

export function applyFilters(points: FlatPoint[], route: RouteState): FilterResult {
  const base = points.filter((p) => (route.multinode ? true : !p.isMultinode))
  if (route.vllm === 'on-target') {
    const onTarget = base.filter((p) => p.onTargetVersion !== false)
    if (onTarget.length === 0 && base.length > 0) {
      // No on-target points in this snapshot — don't show an empty headline; fall back to all.
      return { points: base, onTargetFellBack: true }
    }
    return { points: onTarget, onTargetFellBack: false }
  }
  return { points: base, onTargetFellBack: false }
}
