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

export function applyFilters(points: FlatPoint[], route: RouteState): FlatPoint[] {
  return points.filter((p) => {
    if (!route.multinode && p.isMultinode) return false
    if (route.vllm === 'on-target' && p.onTargetVersion === false) return false
    return true
  })
}
