/**
 * The deep-link scheme, mirroring inference-sim/leaderboard/web/src/route.ts: a hash-carried
 * query so the back button works and a selected row can be linked, screenshotted, or shared
 * (RFC B3: deep-link, row-select → points table, default view). Reader and writer live in one
 * module so they cannot drift.
 *
 *   #/?run=<snapshot_id>&runB=<snapshot_id>&sel=<sweepKey>&grade=<G1|G2|G3|all>&mn=<0|1>
 *
 * `run` selects which published nightly snapshot to view (absent = the latest). Choosing a run
 * only loads older results — it never triggers a new evaluation.
 * `runB` (optional) is the SECOND run for the A-vs-B compare view (RFC discussion #2 point 3):
 * when present, the page shows the per-metric Δ over the points BOTH runs scored, instead of the
 * single-run Overview. Absent = single-run mode (the default; the Overview is untouched).
 * `sel` is the selected topology's sweepKey (model|workload|gpu|topoLabel). Absent = default
 * view (nothing selected). grade is a cumulative filter on the closeness grade: G1, G2 (G1 and G2),
 * G3 (G1 to G3) or all (every graded point, the default). An old link's `tier=` is read as a
 * grade: measured_or_resolved is G1, anything else is all; main.tsx rewrites such a link to
 * `grade=` so it keeps working.
 * mn (multi-node) defaults to 0 (hidden).
 *
 * An old link's `vllm=` parameter (a version filter that no longer exists) is ignored.
 */

/** The cumulative grade filter: a point is shown when its grade is at or above the named one. */
export type GradeFilter = 'G1' | 'G2' | 'G3' | 'all'
export const GRADE_FILTERS: GradeFilter[] = ['G1', 'G2', 'G3', 'all']

export interface RouteState {
  /** Which audience's page: "overview" (outside visitors, the latest run) or "dev" (BLIS
   *  developers: pick and compare runs). #23 */
  view: 'overview' | 'dev'
  /** snapshot_id of the run being viewed, or null for the latest. */
  run: string | null
  /** snapshot_id of the second run to compare against (A-vs-B); null = single-run mode. */
  runB: string | null
  sel: string | null
  /** The closeness grades shown, cumulatively. */
  grade: GradeFilter
  multinode: boolean
}

export const DEFAULT_ROUTE: RouteState = {
  view: 'overview',
  run: null,
  runB: null,
  sel: null,
  grade: 'all',
  multinode: false,
}

function query(hash: string): URLSearchParams {
  const q = hash.indexOf('?')
  return new URLSearchParams(q < 0 ? '' : hash.slice(q + 1))
}

export function parseRoute(hash: string): RouteState {
  const p = query(hash)
  const g = p.get('grade')
  const legacy = p.get('tier')
  const grade: GradeFilter =
    g === 'G1' || g === 'G2' || g === 'G3' ? g : g === null && legacy === 'measured_or_resolved' ? 'G1' : 'all'
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
    grade,
    multinode: p.get('mn') === '1',
  }
}

export function routeToHash(state: RouteState): string {
  const p = new URLSearchParams()
  if (state.view === 'dev') p.set('view', 'dev')
  if (state.run) p.set('run', state.run)
  if (state.runB) p.set('runB', state.runB)
  if (state.sel) p.set('sel', state.sel)
  if (state.grade !== DEFAULT_ROUTE.grade) p.set('grade', state.grade)
  if (state.multinode) p.set('mn', '1')
  const qs = p.toString()
  return qs ? `#/?${qs}` : '#/'
}
