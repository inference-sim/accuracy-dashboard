/**
 * Apply the UI filters to the flat points before aggregation + regrouping. Because every
 * aggregate is recomputed from the surviving points (RFC §4.4/B3), filtering here is the only
 * place a point is hidden — nothing downstream reads a stored parent number.
 *
 * vLLM version is a per-row facet + filter (not a group): "all" shows every version, or a
 * specific version isolates it. Multi-node is hidden by default. The tier switch is applied at
 * aggregation time (a point carries its own tier), not here, so both tiers stay available.
 */
import type { FlatPoint } from './aggregate'
import type { RouteState } from './route'

export function applyFilters(points: FlatPoint[], route: RouteState): FlatPoint[] {
  return points.filter((p) => {
    if (!route.multinode && p.isMultinode) return false
    if (typeof route.vllm === 'object' && p.engineVersion !== route.vllm.version) return false
    return true
  })
}
