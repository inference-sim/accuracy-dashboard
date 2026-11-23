/**
 * The Overview page — two tables (summary drill-down + points), the only page in v0.1.0
 * (RFC §4.5, M4). No plots. Every number is recomputed client-side from the visible points so
 * a filter never shows a stale aggregate (B3). State (selected row, tier, filters) lives in
 * the URL hash for deep-linking (route.ts).
 */
import { useEffect, useMemo, useState } from 'react'
import { flattenPoints, aggregatePair, latestPerConfig, type FlatPoint } from './aggregate'
import { applyFilters } from './filter'
import { ErrorBoundary } from './components/ErrorBoundary'
import { PointsTable } from './components/PointsTable'
import { SummaryTable } from './components/SummaryTable'
import { Dropdown } from './components/Dropdown'
import { Compare } from './components/Compare'
import { Headline } from './components/Headline'
import { Slices } from './components/Slices'
import { gateHeadline, MIN_ROLE_KEYS } from './slice'
import { Classes } from './components/Classes'
import { Sources } from './components/Sources'
import { FunnelNotPublished, fetchFunnel, shouldFetchFunnel, type FunnelDoc } from './sources'
import { fetchClasses, shouldFetchClasses, type ClassesDoc } from './classes'
import { Term } from './components/Term'
import { GRADE_LABELS, inGrade } from './gradeFilter'
import { formatCount } from './format'
import type { RunIndex, RunRef } from './load'
import { DEFAULT_ROUTE, GRADE_FILTERS, parseRoute, routeToHash, type RouteState } from './route'
import { buildRows } from './tree'
import { nextSort, sortModelKeys, type SortKey, type SortSpec } from './sort'
import { isEstimated, type GroundTruthSource, type Summary, type TierKey } from './types'

interface Picker {
  index: RunIndex | null
  run: string | null
  onPick: (run: string | null) => void
  /** second slot (A-vs-B compare); null = single-run mode. */
  runB: string | null
  onPickB: (runB: string | null) => void
}

const hasWindow = typeof window !== 'undefined'

export function App({
  summary,
  summaryB = null,
  loadError,
  index = null,
  initialHash,
  classes = null,
  classesError = null,
  funnel = null,
  funnelError = null,
}: {
  summary: Summary | null
  /** The second run's snapshot for the A-vs-B compare view; null = single-run mode. */
  summaryB?: Summary | null
  loadError: string | null
  /** The retained-runs manifest for the run-picker; null = no index published (latest only). */
  index?: RunIndex | null
  /** Test/SSR seam: the starting hash when there is no window. In the browser the live hash wins. */
  initialHash?: string
  /** Test seam: the classes page's data. In the browser it is fetched when the Classes tab opens. */
  classes?: ClassesDoc | null
  classesError?: string | null
  /** Test seam: the sources page's data (funnel.json). In the browser it is fetched when the Sources tab opens. */
  funnel?: FunnelDoc | null
  funnelError?: string | null
}) {
  const [route, setRoute] = useState<RouteState>(() =>
    parseRoute(hasWindow ? window.location.hash : (initialHash ?? '')),
  )
  const [sort, setSort] = useState<SortSpec | null>(null)
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set())
  const [classesDoc, setClassesDoc] = useState<ClassesDoc | null>(classes)
  const [classesFail, setClassesFail] = useState<string | null>(classesError)
  const [funnelDoc, setFunnelDoc] = useState<FunnelDoc | null>(funnel)
  const [funnelFail, setFunnelFail] = useState<string | null>(funnelError)
  const [funnelMissing, setFunnelMissing] = useState(false)

  useEffect(() => {
    if (!hasWindow) return
    const onHash = () => setRoute(parseRoute(window.location.hash))
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])

  // The classes page's data loads when its tab opens (the Overview never needs it), once, from the same site as the summary.
  useEffect(() => {
    if (!shouldFetchClasses(route.view, classesDoc, classesFail, hasWindow)) return
    let live = true
    fetchClasses()
      .then((doc) => live && setClassesDoc(doc))
      .catch((e: Error) => live && setClassesFail(e.message))
    return () => {
      live = false
    }
  }, [route.view, classesDoc, classesFail])

  // The sources page's data loads when its tab opens, once, from the same site as the summary.
  useEffect(() => {
    if (!shouldFetchFunnel(route.view, funnelDoc, funnelFail, hasWindow)) return
    let live = true
    fetchFunnel()
      .then((doc) => live && setFunnelDoc(doc))
      .catch((e: Error) => {
        if (!live) return
        setFunnelMissing(e instanceof FunnelNotPublished)
        setFunnelFail(e.message)
      })
    return () => {
      live = false
    }
  }, [route.view, funnelDoc, funnelFail])

  const update = (next: Partial<RouteState>) => {
    const merged = { ...route, ...next }
    if (hasWindow) window.location.hash = routeToHash(merged)
    setRoute(merged)
  }

  const picker: Picker = {
    index,
    run: route.run,
    onPick: (run: string | null) => update({ run, sel: null }),
    runB: route.runB,
    // Entering compare: pin A to an EXPLICIT snapshot_id (route.run may be null = "track latest",
    // which can't be diffed reliably). Leaving compare (runB=null): restore the latest-null form so
    // single-run keeps tracking latest. Resolve "latest" → index.runs[0].
    onPickB: (runB: string | null) => {
      if (runB) {
        const aId = route.run ?? index?.runs?.[0]?.snapshot_id ?? null
        update({ run: aId, runB, sel: null })
      } else {
        // back to single-run: if A is the newest snapshot, collapse to null to resume tracking latest
        const latest = index?.runs?.[0]?.snapshot_id ?? null
        update({ run: route.run === latest ? null : route.run, runB: null, sel: null })
      }
    },
  }

  // The classes page reads classes.json only, so it shows even while the summary is still loading.
  if (route.view === 'classes') {
    return (
      <Shell view="classes" onView={(view) => update({ view, runB: null, run: null, sel: null })}>
        <ErrorBoundary resetKey={classesDoc?.generated_at ?? null}>
          <Classes doc={classesDoc} error={classesFail} />
        </ErrorBoundary>
      </Shell>
    )
  }

  // The sources page reads funnel.json only, so it shows even while the summary is still loading.
  if (route.view === 'sources') {
    return (
      <Shell view="sources" onView={(view) => update({ view, runB: null, run: null, sel: null })}>
        <ErrorBoundary resetKey={null}>
          <Sources doc={funnelDoc} error={funnelFail} notPublished={funnelMissing} />
        </ErrorBoundary>
      </Shell>
    )
  }

  if (loadError) {
    return (
      <Shell view={route.view} onView={(view) => update({ view })}>
        <div className="viewerror" role="alert">
          <h3>Could not load this snapshot.</h3>
          <pre>
            <code>{loadError}</code>
          </pre>
        </div>
      </Shell>
    )
  }
  if (!summary) {
    return (
      <Shell view={route.view} onView={(view) => update({ view })}>
        <div className="loading">Loading the snapshot…</div>
      </Shell>
    )
  }

  // Developer view (#23): pick runs and compare them. Kept off the Overview, which is for
  // outside visitors and always shows the latest run.
  if (route.view === 'dev') {
    const comparing = route.runB != null && summaryB != null && summaryB.snapshot_id !== summary.snapshot_id
    return (
      <Shell view="dev" onView={(view) => update({ view, runB: null, run: null, sel: null })}>
        <DevView summary={summary} summaryB={comparing ? summaryB : null} picker={picker}>
          {comparing ? (
            <ErrorBoundary resetKey={route.runB}>
              <Compare a={summary} b={summaryB!} tier="all" />
            </ErrorBoundary>
          ) : (
            <p className="pts-hint">Pick a second run above to see how accuracy changed between them.</p>
          )}
        </DevView>
      </Shell>
    )
  }

  return (
    <Shell view="overview" onView={(view) => update({ view, sel: null })}>
      <ErrorBoundary resetKey={route.sel}>
        <Overview
          summary={summary}
          route={route}
          update={update}
          sort={sort}
          setSort={setSort}
          expanded={expanded}
          setExpanded={setExpanded}
        />
      </ErrorBoundary>
    </Shell>
  )
}

/** The page frame: one column, two tabs. No sidebar: the Overview needs no controls (#23). */
function Shell({
  view,
  onView,
  children,
}: {
  view: 'overview' | 'classes' | 'sources' | 'dev'
  onView: (v: 'overview' | 'classes' | 'sources' | 'dev') => void
  children: React.ReactNode
}) {
  return (
    <div className="page">
      <nav className="tabs" aria-label="Views">
        <button type="button" className={`tab${view === 'overview' ? ' on' : ''}`} onClick={() => onView('overview')}>
          Overview
        </button>
        <button type="button" className={`tab${view === 'classes' ? ' on' : ''}`} onClick={() => onView('classes')}>
          Classes
        </button>
        <button type="button" className={`tab${view === 'sources' ? ' on' : ''}`} onClick={() => onView('sources')}>
          Sources
        </button>
        <button type="button" className={`tab${view === 'dev' ? ' on' : ''}`} onClick={() => onView('dev')}>
          For developers
        </button>
        <a className="ghlink tabs-gh" href="https://github.com/inference-sim/accuracy-dashboard">
          <GithubMark />
          <span>Source</span>
        </a>
      </nav>
      <main className="main">{children}</main>
    </div>
  )
}

function Overview({
  summary,
  route,
  update,
  sort,
  setSort,
  expanded,
  setExpanded,
}: {
  summary: Summary
  route: RouteState
  update: (n: Partial<RouteState>) => void
  sort: SortSpec | null
  setSort: (s: SortSpec | null) => void
  expanded: Set<string>
  setExpanded: (s: Set<string>) => void
}) {
  // The single-run view is the live view: for each config (deployment × concurrency) it shows
  // only the newest measurement (Discussion #15, Decided). Older measurements stay in the snapshot
  // and in Compare (which flattens independently), so release-over-release diffs still see every
  // measurement. v1 dump points have no measured_date and pass through untouched.
  const allPoints = useMemo(() => latestPerConfig(flattenPoints(summary)), [summary])
  const visible = useMemo(() => applyFilters(allPoints, route), [allPoints, route])

  // The grade filter is cumulative (G1, up to G2, up to G3, all graded) and defaults to all graded.
  // Every aggregate is recomputed over the points it keeps, so the table, the points and the
  // counts agree with the grades the control names.
  const inTier = (p: FlatPoint) => inGrade(p, route.grade)
  // The slices are cut from the same points as the table (grade and multi-node filters), before the drilled-in slice narrows them.
  const sliceable = useMemo(
    () => applyFilters(allPoints, { ...route, by: null, sv: null }).filter(inTier),
    [allPoints, route],
  )
  const noneAtGrade = route.grade !== 'all' && visible.length > 0 && !visible.some(inTier)

  // The headline always describes the full latest run under the default view (every scored
  // point, the "all" tier), never the current filter, so the top-line "how accurate is BLIS?"
  // number can't shift under a control (PR #26 review) and matches the point count beside it.
  // Only the per-model table and the points below respond to the filters.
  const headlinePoints = useMemo(() => applyFilters(allPoints, DEFAULT_ROUTE), [allPoints])
  const headlineTier: TierKey = 'all'
  const totals = useMemo(() => aggregatePair(headlinePoints, summary.min_points ?? 0), [headlinePoints, summary.min_points])
  const headlineSplit = useMemo(() => {
    const estimated = headlinePoints.filter((p) => isEstimated(p.fidelity)).length
    return { exact: headlinePoints.length - estimated, estimated }
  }, [headlinePoints])

  // A row is listed only if it has points in the tier being shown, so the exact tier never shows
  // deployments that are entirely estimated as rows of dashes.
  const tierPoints = useMemo(() => visible.filter(inTier), [visible, route.grade])
  const rows = useMemo(() => buildRows(tierPoints, expanded, summary.min_points ?? 0), [tierPoints, expanded, summary.min_points])

  // Sort reorders only the model-level rows; children follow their parent.
  const orderedRows = useMemo(() => {
    const modelRows = rows.filter((r) => r.level === 'model')
    const order = sortModelKeys(modelRows, sort, 'all')
    const rank = new Map(order.map((label, i) => [label, i]))
    // Stable: group rows by their owning model, then emit models in sorted order.
    const byModel = new Map<string, typeof rows>()
    let currentModel = ''
    for (const r of rows) {
      if (r.level === 'model') currentModel = r.label
      const arr = byModel.get(currentModel) ?? []
      arr.push(r)
      byModel.set(currentModel, arr)
    }
    return [...byModel.entries()]
      .sort((a, b) => (rank.get(a[0]) ?? 0) - (rank.get(b[0]) ?? 0))
      .flatMap(([, rs]) => rs)
  }, [rows, sort])

  const onToggle = (id: string) => {
    const next = new Set(expanded)
    if (next.has(id)) next.delete(id)
    else next.add(id)
    setExpanded(next)
  }

  // The selected topology's points, by sweepKey.
  const selectedPoints: FlatPoint[] = useMemo(() => {
    if (!route.sel) return []
    return visible.filter(inTier).filter((p) => p.sweepKey === route.sel)
  }, [visible, route.sel, route.grade])

  const selFirst = selectedPoints[0]
  const pointsTitle = selFirst
    ? `Points — ${selFirst.model} › ${selFirst.workloadLabel} › ${selFirst.gpu} › ${selFirst.topoLabel}`
    : 'Points'
  // A ?sel= that resolves to zero points (deep-linked a row not in THIS snapshot, or hidden by the
  // current tier/version filter) must not read like "nothing selected" (PR #3 review UI-c).
  const selMissing = route.sel != null && selectedPoints.length === 0

  const cov = summary.coverage
  const minRoleKeys = summary.min_points ?? MIN_ROLE_KEYS

  return (
    <>
      <h1 className="pagetitle">BLIS Accuracy</h1>
      <p className="dek">
        How closely BLIS, an LLM inference-serving simulator, predicts real latency, checked against
        InferenceX benchmark measurements on the same model, hardware and load.
      </p>

      <Headline
        totals={totals}
        tier={headlineTier}
        points={headlinePoints.length}
        models={summary.matrix.length}
        blisRelease={summary.provenance?.blis?.release ?? null}
        dataDate={summary.provenance?.ground_truth?.release_tag?.replace(/^db-dump\//, '') ?? null}
        measuredRange={measuredRange(headlinePoints)}
        pulledAt={summary.provenance?.pulled_at ?? null}
        sources={summary.provenance?.ground_truth?.sources ?? null}
        split={summary.schema_version === 2 ? headlineSplit : null}
        graded={summary.headline ? gateHeadline(summary.headline, headlinePoints, summary.min_points ?? MIN_ROLE_KEYS) : null}
      />

      {summary.schema_version === 3 && (
        <Slices
          points={sliceable}
          by={route.by}
          sv={route.sv}
          min={minRoleKeys}
          notScored={summary.not_scored ?? []}
          onBy={(by) => update({ by, sv: null, sel: null })}
          onSv={(sv) => update({ sv, sel: null })}
        />
      )}

      <h2 className="sectitle">Accuracy by model</h2>
      {/* Filters sit beside the table they change; the headline above ignores them (PR #26 review). */}
      <div className="chips">
        <span className="flt">
        <Term name="gradeFilter" />{' '}
        <span className="tierseg">
          {GRADE_FILTERS.map((g) => (
            <span key={g} className={`clk ${route.grade === g ? 'on' : ''}`} onClick={() => update({ grade: g, sel: null })}>
              {GRADE_LABELS[g]}
            </span>
          ))}
        </span>
        {noneAtGrade && <span className="disabled-note">(no points at this grade yet — pick all graded)</span>}
      </span>
    </div>

      <SummaryTable
        rows={orderedRows}
        tier="all"
        sort={sort}
        onSort={(k: SortKey) => setSort(nextSort(sort, k))}
        selectedId={route.sel ? findIdForSweep(orderedRows, route.sel) : null}
        onToggle={onToggle}
        onSelect={(sweepKey) => update({ sel: sweepKey })}
        expanded={expanded}
      />

      <PointsTable
        points={selectedPoints}
        title={pointsTitle}
        selMissing={selMissing}
        minRoleKeys={summary.schema_version === 3 ? minRoleKeys : undefined}
      />

      {/* Every number on this page, per point, with what each one was compared against. */}
      <a className="dl" href="data/latest/summary.json" download="blis-accuracy-results.json">
        ⤓ Download all results (JSON)
      </a>

      <details className="about">
        <summary>How this was measured</summary>
        <p>
          Each InferenceX measurement is one benchmark run on a real vLLM server at one concurrency. BLIS
          simulates the same deployment and the same requests, and the error is how far BLIS's mean latency
          is from the measured one. <b>Error</b> is the average absolute difference; <b>trend error</b> is
          how well BLIS follows the way latency changes with load, ignoring a constant offset. End-to-end,
          tail-latency and throughput accuracy are planned for a future release.
        </p>
        <div className="coverage">
        <span>
          models <b>{formatCount(summary.matrix.length)}</b>
        </span>
        {summary.schema_version === 3 ? (
          <span>
            <Term name="coverage">points graded</Term> <b>{formatCount(cov.graded)}</b> of{' '}
            {formatCount(cov.points)}
          </span>
        ) : (
          <span>
            <Term name="coverage">points scored</Term> <b>{formatCount(cov.scored)}</b>
          </span>
        )}
        <span>
          {/* Only the count: the per-reason breakdown stays in summary.json (coverage.not_scored_reasons). */}
          not scored <b>{formatCount(cov.not_scored)}</b>
        </span>
        {cov.measured_excluded != null && (
          <span>
            excluded (measured) <b>{formatCount(cov.measured_excluded)}</b>
          </span>
        )}
        {summary.schema_version === 3 && cov.failed > 0 && (
          <span>
            failed <b>{formatCount(cov.failed)}</b>
          </span>
        )}
        {summary.schema_version === 1 && (
          // v2 has no hidden or failed buckets: a multi-node or failed point is not scored, with its
          // reason, and counted in the not-scored line above.
          <>
            <span>
              multi-node <b>{formatCount(cov.multinode_hidden)}</b> (hidden)
            </span>
            <span>
              failed <b>{formatCount(cov.failed)}</b>
            </span>
          </>
        )}
        </div>
        <div className="about-prov"><RunProvenance summary={summary} /></div>
      </details>
    </>
  )
}

/** The oldest and newest measurement date among the points (v2 only; v1 points carry none). */
function measuredRange(points: FlatPoint[]): { from: string; to: string } | null {
  const dates = points.map((p) => p.measuredDate).filter((d): d is string => !!d).sort()
  return dates.length ? { from: dates[0]!, to: dates[dates.length - 1]! } : null
}

function findIdForSweep(rows: ReturnType<typeof buildRows>, sweepKey: string): string | null {
  const match = rows.find((r) => r.level === 'topology' && r.sweepKey === sweepKey)
  return match?.id ?? null
}

/** One run's provenance (BLIS release/commit/catalog/kernel/registry + ground-truth dump + run id).
 *  Reused for the single-run rail and both columns of the A-vs-B compare rail. */
function RunProvenance({ summary }: { summary: Summary }) {
  const p = summary.provenance
  if (!p) return null
  // Null-safe reads (PR #3 review UI-b): validateSummary now rejects a malformed provenance up
  // front, but the rail still optional-chains every field so a partial summary that slips through
  // renders the page shell with em dashes — never a blank page (the rail sits outside ErrorBoundary).
  const b = p.blis ?? ({} as Partial<NonNullable<typeof p.blis>>)
  const gt = p.ground_truth ?? ({} as Partial<NonNullable<typeof p.ground_truth>>)
  const dash = (s: string | null | undefined, fn: (v: string) => string = (v) => v) => (s ? fn(s) : '—')
  const range = measuredRange(flattenPoints(summary))
  // Each identifier links to exactly what was run, so nobody has to hunt for the release or
  // commit by hand (PR #26 review). Missing values stay a plain em dash, never a dead link.
  const gh = 'https://github.com/inference-sim'
  const link = (text: string, href: string | null) =>
    href ? (
      <a href={href} target="_blank" rel="noreferrer">
        {text}
      </a>
    ) : (
      text
    )
  // The kernel row names a released kernel and links to its tag. A build the extractor could not name ("...@unknown", which
  // is every build by commit) has no kernel to show, and "unknown" would link to a tag that does not exist: no row then.
  const kernelRaw = b.extractor_version?.replace(/^.*@/, '') ?? null
  const kernel = kernelRaw && kernelRaw.toLowerCase() !== 'unknown' ? kernelRaw : null
  return (
    <>
      <div className="seclabel">BLIS release (CI-resolved)</div>
      <span className="pill">
        {b.release ? link(b.release, `${gh}/inference-sim/releases/tag/${encodeURIComponent(b.release)}`) : '—'}
      </span>
      <div className="kv" style={{ marginTop: 10 }}>
        <span className="k">commit</span>
        <span className="v">
          {b.commit_sha ? link(`${b.commit_sha.slice(0, 7)}…`, `${gh}/inference-sim/commit/${b.commit_sha}`) : '—'}
        </span>
      </div>
      <div className="kv">
        <span className="k">catalog</span>
        <span className="v">
          {b.catalog ? link(b.catalog, `${gh}/blis-catalog/tree/${encodeURIComponent(b.catalog)}`) : '—'}
        </span>
      </div>
      {kernel ? (
        <div className="kv">
          <span className="k">kernel</span>
          <span className="v">{link(kernel, `${gh}/blis-latency-kernel/releases/tag/${encodeURIComponent(kernel)}`)}</span>
        </div>
      ) : null}
      <div className="kv">
        <span className="k">registry</span>
        <span className="v">
          {b.registry ? link(b.registry, `${gh}/blis-registry/releases/tag/${encodeURIComponent(b.registry)}`) : '—'}
        </span>
      </div>
      <div className="seclabel">Ground truth</div>
      <div className="kv">
        <span className="k">source</span>
        <span className="v">
          {p.ingest === 'api' ? link('InferenceX', INFERENCEX_SITE) : 'InferenceX'}
        </span>
      </div>
      {p.ingest === 'api' ? (
        // v2: the data is a pull of the live API, not a dump. When it was pulled, and the span of
        // measurement dates it holds, are two different things, so each gets its own label.
        // With provenance.ground_truth.sources, each source lists its own dates and its own pull date.
        gt.sources?.length ? (
          <SourceRows sources={gt.sources} />
        ) : (
        <>
          <div className="kv">
            <span className="k">API pull date</span>
            <span className="v">
              {p.pulled_at ? `${p.pulled_at.slice(0, 10)} ${p.pulled_at.slice(11, 16)} UTC` : '—'}
            </span>
          </div>
          {range && (
            <div className="kv">
              <span className="k">data range</span>
              <span className="v">{range.from === range.to ? range.to : `${range.from} to ${range.to}`}</span>
            </div>
          )}
          <div className="kv">
            <span className="k">pull sha256</span>
            <span className="v">{dash(gt.measurement_sha256, (v) => `${v.slice(0, 8)}…`)}</span>
          </div>
        </>
        )
      ) : (
        <>
          <div className="kv">
            <span className="k">dump</span>
            <span className="v">
              {gt.release_tag ? link(gt.release_tag.replace('db-dump/', ''), safeUrl(gt.source_url)) : '—'}
            </span>
          </div>
          {gt.measurement_date_through && (
            <div className="kv">
              <span className="k">through</span>
              <span className="v">{gt.measurement_date_through}</span>
            </div>
          )}
          <div className="kv">
            <span className="k">sha256</span>
            <span className="v">{dash(gt.measurement_sha256, (v) => `${v.slice(0, 8)}…`)}</span>
          </div>
        </>
      )}
      <div className="seclabel">Run</div>
      <div className="kv">
        <span className="k">{p.ingest === 'api' ? 'latest run date' : 'snapshot'}</span>
        <span className="v">{dash(summary.snapshot_id, (v) => v.slice(0, 10))}</span>
      </div>
      {p.ingest !== 'api' && (
        // v2's generated time is the pull time (shown above as "pulled"), so it isn't repeated.
        <div className="kv">
          <span className="k">generated</span>
          <span className="v">{dash(summary.generated_at, (v) => `${v.slice(11, 16)} UTC`)}</span>
        </div>
      )}
    </>
  )
}

const utc = (t: string) => `${t.slice(0, 10)} ${t.slice(11, 16)} UTC`

/** Each ground-truth source with its own measurement dates and its own pull date, the dump's cutoff beside it. */
function SourceRows({ sources }: { sources: GroundTruthSource[] }) {
  return (
    <>
      {sources.map((x) => (
        <div className="gt-source" key={x.id} data-source={x.id}>
          <div className="gt-source-name">{x.id === 'dump' ? 'InferenceX database dump' : 'InferenceX API feed'}</div>
          <div className="kv">
            <span className="k">{x.id === 'dump' ? 'dump' : 'release'}</span>
            <span className="v">{x.ref.replace(/^db-dump\//, '')}</span>
          </div>
          {x.cutoff && (
            <div className="kv">
              <span className="k">cutoff</span>
              <span className="v" title="Rows measured before this date come from the dump, the rest from the API feed">
                before {x.cutoff}
              </span>
            </div>
          )}
          <div className="kv">
            <span className="k">{x.id === 'dump' ? 'dump pull date' : 'API pull date'}</span>
            <span className="v">{x.pulled_at ? utc(x.pulled_at) : '—'}</span>
          </div>
          <div className="kv">
            <span className="k">data range</span>
            <span className="v">
              {!x.measurement_date_from || !x.measurement_date_through
                ? '—'
                : x.measurement_date_from === x.measurement_date_through
                  ? x.measurement_date_through
                  : `${x.measurement_date_from} to ${x.measurement_date_through}`}
            </span>
          </div>
          <div className="kv">
            <span className="k">{x.id === 'dump' ? 'sha256' : 'pull sha256'}</span>
            <span className="v">{x.ref_sha256 ? `${x.ref_sha256.slice(0, 8)}…` : '—'}</span>
          </div>
        </div>
      ))}
    </>
  )
}

/** The public InferenceX site the API ingest pulls from (its API root isn't a page to visit). */
const INFERENCEX_SITE = 'https://inferencex.semianalysis.com/'

/**
 * A picker option's label: date · BLIS release · ingest. The ingest tag (· API / · dump) is what
 * #15 asks for, so a reader can tell an API-ingest run from a legacy db-dump one at a glance (and
 * understand why Compare refuses to diff the two). An index entry with no ingest field predates the
 * field and is a dump run.
 */
function runLabel(r: RunRef): string {
  const ingest = (r.ingest ?? 'db-dump') === 'api' ? 'API' : 'dump'
  return `${r.snapshot_id.slice(0, 10)} · ${r.blis_release ?? '?'} · ${ingest}`
}

/** source_url comes from the data file, so only an http(s) URL becomes a link. */
function safeUrl(u: string | null | undefined): string | null {
  return u && /^https?:\/\//.test(u) ? u : null
}

/** The GitHub mark (Octicon path), for the repo link in the rail. aria-hidden: the link text names it. */
function GithubMark() {
  return (
    <svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true" focusable="false">
      <path
        fill="currentColor"
        d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z"
      />
    </svg>
  )
}

function DevView({
  summary,
  summaryB = null,
  picker,
  children,
}: {
  summary: Summary
  /** the second run when comparing; both runs' details are then shown side by side. */
  summaryB?: Summary | null
  picker: Picker
  children: React.ReactNode
}) {
  const runs = picker.index?.runs ?? []
  const comparing = summaryB != null
  return (
    <>
      <h1 className="pagetitle">Compare runs</h1>
      <p className="dek">
        For developers: see how accuracy changed between two nightly runs, for example between
        BLIS releases. Only measurements both runs scored are compared.
      </p>
      <div className="devpickers">
        {runs.length >= 1 && (
          <>
            {/* A and B sit side by side (each its own column: label above its dropdown). */}
            <div className="devpicker-col">
              {/* First slot: a nightly run, tagged A in compare mode. The compare view orders the
                  two runs by date, not by slot. picker.run falls back to the latest snapshot. */}
              <div className="seclabel">
                {/* Always tagged A, so adding a B never leaves "which one is A?" (PR #26 review). */}
                <span className="cmp-tag cmp-a">A</span> Nightly run
              </div>
              <Dropdown
                className="runsel"
                ariaLabel="Select the nightly run (A)"
                disabled={runs.length === 1}
                value={picker.run ?? runs[0]!.snapshot_id}
                // A can never be the run already chosen as B — a run must not be compared with itself.
                options={runs
                  .filter((r) => r.snapshot_id !== picker.runB)
                  .map((r, i) => ({
                    value: r.snapshot_id,
                    label: `${runLabel(r)}${i === 0 ? ' · latest' : ''}`,
                  }))}
                // Single-run: picking the latest → null ("track latest", resolves via data/latest).
                // Compare mode: ALWAYS pin the explicit snapshot_id — a null-latest A can't be diffed
                // reliably (data/latest may not be the labelled run), which showed the wrong A.
                onChange={(id) =>
                  picker.onPick(!comparing && id === runs[0]!.snapshot_id ? null : id)
                }
              />
            </div>
            {/* Second slot = run B (compared). Only meaningful with ≥2 retained runs. "none" leaves
                single-run mode (the Overview). */}
            {runs.length >= 2 && (
              <div className="devpicker-col">
                <div className="seclabel">
                  <span className="cmp-tag cmp-b">B</span> Compare against
                </div>
                <Dropdown
                  className="runsel"
                  ariaLabel="Compare against a second run (B)"
                  value={picker.runB ?? '__none__'}
                  options={[
                    { value: '__none__', label: 'none (single run)' },
                    ...runs
                      .filter((r) => r.snapshot_id !== (picker.run ?? runs[0]!.snapshot_id))
                      .map((r) => ({
                        value: r.snapshot_id,
                        label: runLabel(r),
                      })),
                  ]}
                  onChange={(id) => picker.onPickB(id === '__none__' ? null : id)}
                />
              </div>
            )}
            {runs.length > 1 && !comparing && (
              <div className="runsel-note">Viewing an older run shows its full results — it does not re-run.</div>
            )}
          </>
        )}
      </div>
      {children}
      {comparing && (
        <details className="about">
          <summary>Run details</summary>
          <div className="prov-ab">
            <div className="prov-col about-prov">
              <div className="seclabel"><span className="cmp-tag cmp-a">A</span> run</div>
              <RunProvenance summary={summary} />
            </div>
            <div className="prov-col about-prov">
              <div className="seclabel"><span className="cmp-tag cmp-b">B</span> run</div>
              <RunProvenance summary={summaryB!} />
            </div>
          </div>
        </details>
      )}
    </>
  )
}
