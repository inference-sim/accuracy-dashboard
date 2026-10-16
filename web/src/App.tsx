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
import { formatCount } from './format'
import { parseRoute, routeToHash, type RouteState } from './route'
import { buildRows } from './tree'
import { nextSort, sortModelKeys, type SortKey, type SortSpec } from './sort'
import type { Summary } from './types'

const hasWindow = typeof window !== 'undefined'

export function App({
  summary,
  loadError,
  initialHash,
}: {
  summary: Summary | null
  loadError: string | null
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

  if (loadError) {
    return (
      <Layout summary={null}>
        <div className="viewerror" role="alert">
          <h3>Could not load the latest snapshot.</h3>
          <pre>
            <code>{loadError}</code>
          </pre>
        </div>
      </Layout>
    )
  }
  if (!summary) {
    return (
      <Layout summary={null}>
        <div className="loading">Loading the latest snapshot…</div>
      </Layout>
    )
  }

  return (
    <Layout summary={summary}>
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

  // The totals block is recomputed from the visible points too, so the headline matches the
  // filtered view. same_points_delta is a snapshot-level number from the orchestrator.
  const totals = useMemo(() => aggregatePair(visible), [visible])
  const storedDelta = summary.totals.measured_or_resolved.same_points_delta ?? null

  const rows = useMemo(() => buildRows(visible, expanded), [visible, expanded])

  // Sort reorders only the model-level rows; children follow their parent.
  const orderedRows = useMemo(() => {
    const modelRows = rows.filter((r) => r.level === 'model')
    const order = sortModelKeys(modelRows, sort, route.tier)
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
  }, [rows, sort, route.tier])

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
      route.tier === 'all' ? visible : visible.filter((p) => p.tier === 'measured_or_resolved')
    return tierScoped.filter((p) => p.sweepKey === route.sel)
  }, [visible, route.sel, route.tier])

  const selFirst = selectedPoints[0]
  const pointsTitle = selFirst
    ? `Points — ${selFirst.model} › ${selFirst.workloadLabel} › ${selFirst.gpu} › ${selFirst.topoLabel}`
    : 'Points'

  const cov = summary.coverage
  const notScoredDetail = Object.entries(cov.not_scored_reasons || {})
    .map(([k, v]) => `${k.replace(/_/g, ' ')} ${v}`)
    .join(', ')

  return (
    <>
      <h2 className="viewhead">End-to-end accuracy — BLIS vs InferenceX</h2>
      <p className="dek">
        Every number is a full <b>blis replay</b> through the whole stack, scored against the pinned weekly
        InferenceX dump. Two tables: a <b>summary</b> drill-down (model → workload → GPU → topology), and a{' '}
        <b>points</b> table for the selected row (measured vs predicted per concurrency). No pass/fail colouring —
        report, don't assert.
      </p>

      <div className="chips">
        <span
          className={`toggle disabled`}
          title="Enabling multi-node needs a blis-latency-kernel change (RFC §4.5)"
        >
          <span className="sw">
            <span className="dot" />
          </span>
          multi-node <span className="disabled-note">(disabled — needs kernel change)</span>
        </span>
        <span className="flt">
          tier{' '}
          <span className="tierseg">
            <span
              className={`clk ${route.tier === 'measured_or_resolved' ? 'on' : ''}`}
              onClick={() => update({ tier: 'measured_or_resolved' })}
            >
              measured·resolved
            </span>
            <span className={`clk ${route.tier === 'all' ? 'on' : ''}`} onClick={() => update({ tier: 'all' })}>
              all
            </span>
          </span>
        </span>
        <span className="flt">
          vLLM version{' '}
          <span
            className="box clk"
            onClick={() => update({ vllm: route.vllm === 'on-target' ? 'all' : 'on-target' })}
          >
            {route.vllm === 'on-target' ? `on-target v${summary.target_vllm}` : 'all versions'} <span className="car">▾</span>
          </span>
        </span>
      </div>

      <div className="tbl-title">Summary — mean TTFT/TPOT: MAPE &amp; shape</div>
      <SummaryTable
        totals={totals}
        totalsDelta={storedDelta}
        totalsPointCount={visible.length}
        rows={orderedRows}
        tier={route.tier}
        targetVllm={summary.target_vllm}
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
          points scored <b>{formatCount(cov.scored)}</b>
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

      <PointsTable points={selectedPoints} title={pointsTitle} vllm={selFirst?.engineVersion ?? null} onTarget={selFirst?.onTargetVersion ?? null} />

      <div className="legend">
        <span>
          <span className="ver" style={{ margin: 0 }}>
            v{summary.target_vllm}
          </span>{' '}
          on BLIS's target vLLM
        </span>
        <span>
          <span className="ver off" style={{ margin: 0 }}>
            off
          </span>{' '}
          off BLIS's target
        </span>
        <span>
          <b>mape</b> absolute · <b>shape</b> curvature · <b>n</b> points per metric
        </span>
      </div>

      {summary.known_artefacts && summary.known_artefacts.length > 0 && (
        <p className="foot">
          <b>Known measurement artefacts</b> (noted, not dropped — RFC keeps scoring logic out of this repo):{' '}
          {summary.known_artefacts.join('; ')}. v0.1.0 scores mean TTFT and TPOT only (MAPE + shape); E2E, tail p99
          and throughput are planned for a future release. Default view is on-target v{summary.target_vllm}; vLLM
          version is a per-row badge + filter, not a group. Selecting a topology row populates the points table
          (deep-linked via the URL).
        </p>
      )}
    </>
  )
}

function findIdForSweep(rows: ReturnType<typeof buildRows>, sweepKey: string): string | null {
  const match = rows.find((r) => r.level === 'topology' && r.sweepKey === sweepKey)
  return match?.id ?? null
}

function Layout({ summary, children }: { summary: Summary | null; children: React.ReactNode }) {
  const p = summary?.provenance
  return (
    <div className="layout">
      <aside className="rail">
        <h1>BLIS Accuracy</h1>
        <p className="sub">
          How accurately BLIS predicts real inference latency, scored nightly against SemiAnalysis InferenceX.
        </p>
        {p && (
          <>
            <div className="seclabel">BLIS release (CI-resolved)</div>
            <span className="pill">{p.blis.release}</span>
            <div className="kv" style={{ marginTop: 10 }}>
              <span className="k">commit</span>
              <span className="v">{p.blis.commit_sha.slice(0, 7)}…</span>
            </div>
            <div className="kv">
              <span className="k">catalog</span>
              <span className="v">{p.blis.catalog}</span>
            </div>
            <div className="kv">
              <span className="k">kernel</span>
              <span className="v">{p.blis.extractor_version.replace(/^.*@/, '')}</span>
            </div>
            <div className="kv">
              <span className="k">registry</span>
              <span className="v">{p.blis.registry}</span>
            </div>
            <div className="seclabel">Ground truth</div>
            <div className="kv">
              <span className="k">source</span>
              <span className="v">InferenceX</span>
            </div>
            <div className="kv">
              <span className="k">dump</span>
              <span className="v">{p.ground_truth.release_tag.replace('db-dump/', '')}</span>
            </div>
            {p.ground_truth.measurement_date_through && (
              <div className="kv">
                <span className="k">through</span>
                <span className="v">{p.ground_truth.measurement_date_through}</span>
              </div>
            )}
            <div className="kv">
              <span className="k">sha256</span>
              <span className="v">{p.ground_truth.measurement_sha256.slice(0, 8)}…</span>
            </div>
            <div className="seclabel">Run</div>
            <div className="kv">
              <span className="k">snapshot</span>
              <span className="v">{summary!.snapshot_id.slice(0, 10)}</span>
            </div>
            <div className="kv">
              <span className="k">generated</span>
              <span className="v">{summary!.generated_at.slice(11, 16)} UTC</span>
            </div>
            <a className="dl" href="data/latest/summary.json" download>
              ⤓ summary.json
            </a>
          </>
        )}
        <div style={{ marginTop: 18 }}>
          <a href="https://github.com/inference-sim/accuracy-dashboard">↗ inference-sim/accuracy-dashboard</a>
        </div>
      </aside>
      <main className="main">
        <div className="tabs">
          <div className="tab on">Overview</div>
          <div className="tab">About</div>
        </div>
        {children}
      </main>
    </div>
  )
}
