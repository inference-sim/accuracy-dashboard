/**
 * Apply the UI filters to the flat points before aggregation + regrouping. Because every
 * aggregate is recomputed from the surviving points (RFC §4.4/B3), filtering here is the only
 * place a point is hidden — nothing downstream reads a stored parent number.
 *
 * Multi-node is hidden by default. The vLLM version is shown per row, never filtered on. The tier switch is applied at
 * aggregation time (a point carries its own tier), not here, so both tiers stay available.
 */
import type { FlatPoint } from './aggregate'
import type { RouteState } from './route'

export function applyFilters(points: FlatPoint[], route: RouteState): FlatPoint[] {
  return points.filter((p) => {
    if (!route.multinode && p.isMultinode) return false
    return true
  })
}
