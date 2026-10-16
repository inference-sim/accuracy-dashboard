/**
 * The deep-link scheme, mirroring inference-sim/leaderboard/web/src/route.ts: a hash-carried
 * query so the back button works and a selected row can be linked, screenshotted, or shared
 * (RFC B3: deep-link, row-select → points table, default view). Reader and writer live in one
 * module so they cannot drift.
 *
 *   #/?sel=<sweepKey>&tier=<measured_or_resolved|all>&vllm=<on-target|all>&mn=<0|1>
 *
 * `sel` is the selected topology's sweepKey (model|workload|gpu|topoLabel). Absent = default
 * view (nothing selected). tier defaults to measured_or_resolved; vllm defaults to on-target
 * (the default state IS the headline, §6.3); mn (multi-node) defaults to 0 (hidden).
 */
import type { TierKey } from './types'

export interface RouteState {
  sel: string | null
  tier: TierKey
  vllm: 'on-target' | 'all'
  multinode: boolean
}

export const DEFAULT_ROUTE: RouteState = {
  sel: null,
  tier: 'measured_or_resolved',
  vllm: 'on-target',
  multinode: false,
}

function query(hash: string): URLSearchParams {
  const q = hash.indexOf('?')
  return new URLSearchParams(q < 0 ? '' : hash.slice(q + 1))
}

export function parseRoute(hash: string): RouteState {
  const p = query(hash)
  const tier = p.get('tier')
  const vllm = p.get('vllm')
  const sel = p.get('sel')
  return {
    sel: sel && sel !== '' ? sel : null,
    tier: tier === 'all' ? 'all' : 'measured_or_resolved',
    vllm: vllm === 'all' ? 'all' : 'on-target',
    multinode: p.get('mn') === '1',
  }
}

export function routeToHash(state: RouteState): string {
  const p = new URLSearchParams()
  if (state.sel) p.set('sel', state.sel)
  if (state.tier !== DEFAULT_ROUTE.tier) p.set('tier', state.tier)
  if (state.vllm !== DEFAULT_ROUTE.vllm) p.set('vllm', state.vllm)
  if (state.multinode) p.set('mn', '1')
  const qs = p.toString()
  return qs ? `#/?${qs}` : '#/'
}
