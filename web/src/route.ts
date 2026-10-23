/**
 * The deep-link scheme, mirroring inference-sim/leaderboard/web/src/route.ts: a hash-carried
 * query so the back button works and a selected row can be linked, screenshotted, or shared
 * (RFC B3: deep-link, row-select → points table, default view). Reader and writer live in one
 * module so they cannot drift.
 *
 *   #/?run=<snapshot_id>&runB=<snapshot_id>&sel=<sweepKey>&tier=<measured_or_resolved|estimated|all>&mn=<0|1>
 *
 * `run` selects which published nightly snapshot to view (absent = the latest). Choosing a run
 * only loads older results — it never triggers a new evaluation.
 * `runB` (optional) is the SECOND run for the A-vs-B compare view (RFC discussion #2 point 3):
 * when present, the page shows the per-metric Δ over the points BOTH runs scored, instead of the
 * single-run Overview. Absent = single-run mode (the default; the Overview is untouched).
 * `sel` is the selected topology's sweepKey (model|workload|gpu|topoLabel). Absent = default
 * view (nothing selected). tier defaults to all (every scored point); an old link that
 * names no tier opens on all too.
 * mn (multi-node) defaults to 0 (hidden).
 *
 * An old link's `vllm=` parameter (a version filter that no longer exists) is ignored.
 */
import type { TierKey } from './types'

export interface RouteState {
  /** Which audience's page: "overview" (outside visitors, the latest run) or "dev" (BLIS
   *  developers: pick and compare runs). #23 */
  view: 'overview' | 'dev'
  /** snapshot_id of the run being viewed, or null for the latest. */
  run: string | null
  /** snapshot_id of the second run to compare against (A-vs-B); null = single-run mode. */
  runB: string | null
  sel: string | null
  /** The tier shown. 'estimated' (v2 only) is a view: just the points BLIS estimated. */
  tier: TierKey | 'estimated'
  multinode: boolean
}

export const DEFAULT_ROUTE: RouteState = {
  view: 'overview',
  run: null,
  runB: null,
  sel: null,
  tier: 'all',
  multinode: false,
}

function query(hash: string): URLSearchParams {
  const q = hash.indexOf('?')
  return new URLSearchParams(q < 0 ? '' : hash.slice(q + 1))
}

export function parseRoute(hash: string): RouteState {
  const p = query(hash)
  const tier = p.get('tier')
  const sel = p.get('sel')
  const run = p.get('run')
  const runB = p.get('runB')
  // A link from before the developer tab existed that names a second run still opens the
  // comparison, so old shared links keep working.
  const view = p.get('view') === 'dev' || (runB && runB !== '') ? 'dev' : 'overview'
  return {
    view,
    run: run && run !== '' ? run : null,
    runB: runB && runB !== '' ? runB : null,
    sel: sel && sel !== '' ? sel : null,
    tier: tier === 'measured_or_resolved' ? 'measured_or_resolved' : tier === 'estimated' ? 'estimated' : 'all',
    multinode: p.get('mn') === '1',
  }
}

export function routeToHash(state: RouteState): string {
  const p = new URLSearchParams()
  if (state.view === 'dev') p.set('view', 'dev')
  if (state.run) p.set('run', state.run)
  if (state.runB) p.set('runB', state.runB)
  if (state.sel) p.set('sel', state.sel)
  if (state.tier !== DEFAULT_ROUTE.tier) p.set('tier', state.tier)
  if (state.multinode) p.set('mn', '1')
  const qs = p.toString()
  return qs ? `#/?${qs}` : '#/'
}
