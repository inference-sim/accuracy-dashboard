/**
 * The deep-link scheme, mirroring inference-sim/leaderboard/web/src/route.ts: a hash-carried
 * query so the back button works and a selected row can be linked, screenshotted, or shared
 * (RFC B3: deep-link, row-select → points table, default view). Reader and writer live in one
 * module so they cannot drift.
 *
 *   #/?sel=<sweepKey>&tier=<measured_or_resolved|all>&vllm=<all|v:X.Y.Z>&mn=<0|1>
 *
 * `sel` is the selected topology's sweepKey (model|workload|gpu|topoLabel). Absent = default
 * view (nothing selected). tier defaults to measured_or_resolved; vllm defaults to all;
 * mn (multi-node) defaults to 0 (hidden).
 *
 * vllm is a filter (§4.5): "all" (every version) or a specific pinned version carried as
 * "v:<version>" so a single version can be isolated. The version is a per-row facet, not a group.
 */
import type { TierKey } from './types'

/** 'all' | { version: '0.29.0' } — the latter isolates one specific vLLM version. */
export type VllmFilter = 'all' | { version: string }

export interface RouteState {
  sel: string | null
  tier: TierKey
  vllm: VllmFilter
  multinode: boolean
}

export const DEFAULT_ROUTE: RouteState = {
  sel: null,
  tier: 'measured_or_resolved',
  vllm: 'all',
  multinode: false,
}

function query(hash: string): URLSearchParams {
  const q = hash.indexOf('?')
  return new URLSearchParams(q < 0 ? '' : hash.slice(q + 1))
}

function parseVllm(raw: string | null): VllmFilter {
  if (raw && raw.startsWith('v:') && raw.length > 2) return { version: raw.slice(2) }
  return 'all'
}

function vllmToParam(v: VllmFilter): string {
  return typeof v === 'object' ? `v:${v.version}` : 'all'
}

export function parseRoute(hash: string): RouteState {
  const p = query(hash)
  const tier = p.get('tier')
  const sel = p.get('sel')
  return {
    sel: sel && sel !== '' ? sel : null,
    tier: tier === 'all' ? 'all' : 'measured_or_resolved',
    vllm: parseVllm(p.get('vllm')),
    multinode: p.get('mn') === '1',
  }
}

export function routeToHash(state: RouteState): string {
  const p = new URLSearchParams()
  if (state.sel) p.set('sel', state.sel)
  if (state.tier !== DEFAULT_ROUTE.tier) p.set('tier', state.tier)
  if (state.vllm !== DEFAULT_ROUTE.vllm) p.set('vllm', vllmToParam(state.vllm))
  if (state.multinode) p.set('mn', '1')
  const qs = p.toString()
  return qs ? `#/?${qs}` : '#/'
}
