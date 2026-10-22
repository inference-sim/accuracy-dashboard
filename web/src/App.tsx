/**
 * The Overview page — two tables (summary drill-down + points), the only page in v0.1.0
 * (RFC §4.5, M4). No plots. Every number is recomputed client-side from the visible points so
 * a filter never shows a stale aggregate (B3). State (selected row, tier, filters) lives in
 * the URL hash for deep-linking (route.ts).
 */
import { useEffect, useMemo, useState } from 'react'
import { flattenPoints, aggregatePair, type FlatPoint } from './aggregate'
import { applyFilters } from './filter'
import { ErrorBoundary } from './components/ErrorBoundary'
import { PointsTable } from './components/PointsTable'
import { SummaryTable } from './components/SummaryTable'
import { Dropdown } from './components/Dropdown'
import { Compare } from './components/Compare'
import { Term } from './components/Term'
import { formatCount, formatVersion } from './format'
import type { RunIndex } from './load'
import { parseRoute, routeToHash, type RouteState } from './route'
import { buildRows } from './tree'
import { nextSort, sortModelKeys, type SortKey, type SortSpec } from './sort'
import type { Summary } from './types'

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
}: {
  summary: Summary | null
  /** The second run's snapshot for the A-vs-B compare view; null = single-run mode. */
  summaryB?: Summary | null
  loadError: string | null
  /** The retained-runs manifest for the run-picker; null = no index published (latest only). */
  index?: RunIndex | null
  /** Test/SSR seam: the starting hash when there is no window. In the browser the live hash wins. */
  initialHash?: string
}) {
  const [route, setRoute] = useState<RouteState>(() =>
    parseRoute(hasWindow ? window.location.hash : (initialHash ?? '')),
  )
  const [sort, setSort] = useState<SortSpec | null>(null)
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set())

  useEffect(() => {
    if (!hasWindow) return
    const onHash = () => setRoute(parseRoute(window.location.hash))
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])

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

  if (loadError) {
    return (
      <Layout summary={null} picker={picker}>
        <div className="viewerror" role="alert">
          <h3>Could not load this snapshot.</h3>
          <pre>
            <code>{loadError}</code>
          </pre>
        </div>
      </Layout>
    )
  }
  if (!summary) {
    return (
      <Layout summary={null} picker={picker}>
        <div className="loading">Loading the snapshot…</div>
      </Layout>
    )
  }

  // A-vs-B compare mode: entered only when a second run is chosen AND its snapshot has loaded, and
  // the two runs are DIFFERENT (a run compared with itself is meaningless — guard a hand-crafted
  // run=X&runB=X URL by falling through to the single-run Overview). The dropdowns already prevent
  // picking the same run on both sides. The single-run path below is otherwise unchanged.
  if (route.runB && summaryB && summaryB.snapshot_id !== summary.snapshot_id) {
    return (
      <Layout summary={summary} summaryB={summaryB} picker={picker}>
        <ErrorBoundary resetKey={route.runB}>
          <Compare a={summary} b={summaryB} tier={route.tier} />
        </ErrorBoundary>
      </Layout>
    )
  }

  return (
    <Layout summary={summary} picker={picker}>
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
    </Layout>
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
  const allPoints = useMemo(() => flattenPoints(summary), [summary])
  const visible = useMemo(() => applyFilters(allPoints, route), [allPoints, route])

  // Distinct vLLM versions present in the snapshot, for the version dropdown (§4.5: version is a
  // per-row filter). Sorted; the dropdown offers "all versions" + each of these.
  const versions = useMemo(
    () => [...new Set(allPoints.map((p) => p.engineVersion).filter((v): v is string => !!v))].sort(),
    [allPoints],
  )

  // Effective tier: the default is measured_or_resolved, but if a snapshot has zero
  // measured-or-resolved points (the direct dump path leaves settings resolved, so every point
  // lands in "all") we fall back to the "all" tier rather than show an empty headline. The
  // user's explicit tier click is always honoured; this only rescues the DEFAULT.
  const tierFellBack =
    route.tier === 'measured_or_resolved' &&
    visible.filter((p) => p.tier === 'measured_or_resolved').length === 0 &&
    visible.length > 0
  const effectiveTier = tierFellBack ? 'all' : route.tier

  // The totals block is recomputed from the visible points so the headline matches the filtered view.
  const totals = useMemo(() => aggregatePair(visible), [visible])

  const rows = useMemo(() => buildRows(visible, expanded), [visible, expanded])

  // Sort reorders only the model-level rows; children follow their parent.
  const orderedRows = useMemo(() => {
    const modelRows = rows.filter((r) => r.level === 'model')
    const order = sortModelKeys(modelRows, sort, effectiveTier)
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
  }, [rows, sort, effectiveTier])

  const onToggle = (id: string) => {
    const next = new Set(expanded)
    if (next.has(id)) next.delete(id)
    else next.add(id)
    setExpanded(next)
  }

  // The selected topology's points, by sweepKey.
  const selectedPoints: FlatPoint[] = useMemo(() => {
    if (!route.sel) return []
    const tierScoped =
      effectiveTier === 'all' ? visible : visible.filter((p) => p.tier === 'measured_or_resolved')
    return tierScoped.filter((p) => p.sweepKey === route.sel)
  }, [visible, route.sel, effectiveTier])

  const selFirst = selectedPoints[0]
  const pointsTitle = selFirst
    ? `Points — ${selFirst.model} › ${selFirst.workloadLabel} › ${selFirst.gpu} › ${selFirst.topoLabel}`
    : 'Points'
  // A ?sel= that resolves to zero points (deep-linked a row not in THIS snapshot, or hidden by the
  // current tier/version filter) must not read like "nothing selected" (PR #3 review UI-c).
  const selMissing = route.sel != null && selectedPoints.length === 0

  const cov = summary.coverage
  const notScoredDetail = Object.entries(cov.not_scored_reasons || {})
    .map(([k, v]) => `${k.replace(/_/g, ' ')} ${v}`)
    .join(', ')

  return (
    <>
      <h2 className="viewhead">How accurate is BLIS?</h2>
      <p className="dek">
        BLIS simulates LLM inference serving. Here, each of its latency predictions is checked against a
        real measurement from InferenceX benchmarks, on the same model, hardware and load. Lower error is
        better.
      </p>

      <div className="chips">
        <span className="flt">
          <Term name="tier" />{' '}
          <span className="tierseg">
            {/* The highlighted option is the one actually shown: when the stricter tier has no
                points the view falls back to "all", so "all" is highlighted then (#23). */}
            <span
              className={`clk ${effectiveTier === 'measured_or_resolved' ? 'on' : ''}`}
              onClick={() => update({ tier: 'measured_or_resolved' })}
            >
              measured·resolved
            </span>
            <span className={`clk ${effectiveTier === 'all' ? 'on' : ''}`} onClick={() => update({ tier: 'all' })}>
              all
            </span>
          </span>
          {tierFellBack && <span className="disabled-note">(no measured·resolved points yet — showing all)</span>}
        </span>
        <span className="flt">
          vLLM version{' '}
          <Dropdown
            className="vllmsel"
            ariaLabel="Filter by vLLM version"
            value={typeof route.vllm === 'object' ? `v:${route.vllm.version}` : 'all'}
            options={[
              { value: 'all', label: 'all versions' },
              ...versions.map((v) => ({ value: `v:${v}`, label: formatVersion(v) })),
            ]}
            onChange={(v) => update({ vllm: v === 'all' ? 'all' : { version: v.replace(/^v:/, '') } })}
          />
        </span>
      </div>

      <div className="tbl-title">Summary — mean TTFT/TPOT: MAPE &amp; shape</div>
      <SummaryTable
        totals={totals}
        totalsPointCount={visible.length}
        rows={orderedRows}
        tier={effectiveTier}
        sort={sort}
        onSort={(k: SortKey) => setSort(nextSort(sort, k))}
        selectedId={route.sel ? findIdForSweep(orderedRows, route.sel) : null}
        onToggle={onToggle}
        onSelect={(sweepKey) => update({ sel: sweepKey })}
        expanded={expanded}
      />

      <div className="gate-legend">E2E, tail-latency and throughput accuracy are planned for a future release.</div>

      <div className="coverage" style={{ margin: '14px 0 4px' }}>
        <span>
          models <b>{formatCount(summary.matrix.length)}</b>
        </span>
        <span>
          <Term name="coverage">points scored</Term> <b>{formatCount(cov.scored)}</b>
        </span>
        <span>
          not scored <b>{formatCount(cov.not_scored)}</b>{' '}
          {notScoredDetail && <span className="nscov">({notScoredDetail})</span>}
        </span>
        {cov.measured_excluded != null && (
          <span>
            excluded (measured) <b>{formatCount(cov.measured_excluded)}</b>
          </span>
        )}
        <span>
          multi-node <b>{formatCount(cov.multinode_hidden)}</b> (hidden)
        </span>
        <span>
          failed <b>{formatCount(cov.failed)}</b>
        </span>
      </div>

      <PointsTable points={selectedPoints} title={pointsTitle} selMissing={selMissing} />

      <div className="legend">
        <span>
          <span className="ver" style={{ margin: 0 }}>
            vX.Y.Z
          </span>{' '}
          the row's measured vLLM version
        </span>
        <span>
          <Term name="mape"><b>mape</b></Term> absolute · <Term name="shape"><b>shape</b></Term> curvature
        </span>
      </div>
    </>
  )
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
  return (
    <>
      <div className="seclabel">BLIS release (CI-resolved)</div>
      <span className="pill">{b.release ?? '—'}</span>
      <div className="kv" style={{ marginTop: 10 }}>
        <span className="k">commit</span>
        <span className="v">{dash(b.commit_sha, (v) => `${v.slice(0, 7)}…`)}</span>
      </div>
      <div className="kv">
        <span className="k">catalog</span>
        <span className="v">{b.catalog ?? '—'}</span>
      </div>
      <div className="kv">
        <span className="k">kernel</span>
        <span className="v">{dash(b.extractor_version, (v) => v.replace(/^.*@/, ''))}</span>
      </div>
      <div className="kv">
        <span className="k">registry</span>
        <span className="v">{b.registry ?? '—'}</span>
      </div>
      <div className="seclabel">Ground truth</div>
      <div className="kv">
        <span className="k">source</span>
        <span className="v">InferenceX</span>
      </div>
      <div className="kv">
        <span className="k">dump</span>
        <span className="v">{dash(gt.release_tag, (v) => v.replace('db-dump/', ''))}</span>
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
      <div className="seclabel">Run</div>
      <div className="kv">
        <span className="k">snapshot</span>
        <span className="v">{dash(summary.snapshot_id, (v) => v.slice(0, 10))}</span>
      </div>
      <div className="kv">
        <span className="k">generated</span>
        <span className="v">{dash(summary.generated_at, (v) => `${v.slice(11, 16)} UTC`)}</span>
      </div>
    </>
  )
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

const RAIL_COLLAPSED_KEY = 'blis-rail-collapsed'

function Layout({
  summary,
  summaryB = null,
  picker,
  children,
}: {
  summary: Summary | null
  /** present only in A-vs-B compare mode — the rail then shows both runs' provenance side by side. */
  summaryB?: Summary | null
  picker: Picker
  children: React.ReactNode
}) {
  const runs = picker.index?.runs ?? []
  const comparing = summaryB != null

  // The rail is collapsible so the tables can use the full width; the choice is remembered.
  const [collapsed, setCollapsed] = useState<boolean>(() => {
    if (!hasWindow) return false
    try {
      return window.localStorage.getItem(RAIL_COLLAPSED_KEY) === '1'
    } catch {
      return false
    }
  })
  const toggleCollapsed = () => {
    setCollapsed((c) => {
      const next = !c
      if (hasWindow) {
        try {
          window.localStorage.setItem(RAIL_COLLAPSED_KEY, next ? '1' : '0')
        } catch {
          /* storage unavailable (private mode) — the toggle still works for this session */
        }
      }
      return next
    })
  }

  if (collapsed) {
    return (
      <div className="layout collapsed">
        <aside className="rail railmini">
          <button type="button" className="railtoggle" aria-label="Expand sidebar" title="Expand sidebar" onClick={toggleCollapsed}>
            »
          </button>
        </aside>
        <main className="main">{children}</main>
      </div>
    )
  }

  return (
    <div className="layout">
      <aside className="rail">
        <button type="button" className="railtoggle" aria-label="Collapse sidebar" title="Collapse sidebar" onClick={toggleCollapsed}>
          «
        </button>
        <h1>BLIS Accuracy</h1>
        <p className="sub">
          How accurately BLIS predicts real inference latency, scored nightly against SemiAnalysis InferenceX.
        </p>
        {runs.length >= 1 && (
          <>
            {/* First slot: a nightly run, tagged A in compare mode. The compare view orders the two
                runs by date, not by slot. picker.run falls back to the latest snapshot. */}
            <div className="seclabel">
              {comparing && <span className="cmp-tag cmp-a">A</span>} Nightly run
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
                  label: `${r.snapshot_id.slice(0, 10)} · ${r.blis_release ?? '?'}${i === 0 ? ' · latest' : ''}`,
                }))}
              // Single-run: picking the latest → null ("track latest", resolves via data/latest).
              // Compare mode: ALWAYS pin the explicit snapshot_id — a null-latest A can't be diffed
              // reliably (data/latest may not be the labelled run), which showed the wrong A.
              onChange={(id) =>
                picker.onPick(!comparing && id === runs[0]!.snapshot_id ? null : id)
              }
            />
            {runs.length > 1 && !comparing && (
              <div className="runsel-note">Viewing an older run shows its full results — it does not re-run.</div>
            )}
            {/* Second slot = run B (compared). Only meaningful with ≥2 retained runs. "none" leaves
                single-run mode (the Overview). */}
            {runs.length >= 2 && (
              <>
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
                        label: `${r.snapshot_id.slice(0, 10)} · ${r.blis_release ?? '?'}`,
                      })),
                  ]}
                  onChange={(id) => picker.onPickB(id === '__none__' ? null : id)}
                />
                {picker.runB && (
                  <div className="runsel-note">Showing Δ (newer − older) over the points both runs scored.</div>
                )}
              </>
            )}
          </>
        )}
        {/* Single-run: one provenance block (with the summary.json download). Compare mode: both
            runs side by side (A = baseline, B = compared) so the rail never misrepresents which run
            the BLIS release / commit / dump belong to. */}
        {summary &&
          (comparing ? (
            <div className="prov-ab">
              <div className="prov-col">
                <div className="seclabel"><span className="cmp-tag cmp-a">A</span> run</div>
                <RunProvenance summary={summary} />
              </div>
              <div className="prov-col">
                <div className="seclabel"><span className="cmp-tag cmp-b">B</span> run</div>
                <RunProvenance summary={summaryB!} />
              </div>
            </div>
          ) : (
            <>
              <RunProvenance summary={summary} />
              <a className="dl" href="data/latest/summary.json" download>
                ⤓ summary.json
              </a>
            </>
          ))}
        <div style={{ marginTop: 18 }}>
          <a className="ghlink" href="https://github.com/inference-sim/accuracy-dashboard">
            <GithubMark />
            inference-sim/accuracy-dashboard
          </a>
        </div>
      </aside>
      <main className="main">
        {/* Overview is the only page in v0.1.0 (RFC §4.5), so no tab bar. */}
        {children}
      </main>
    </div>
  )
}
