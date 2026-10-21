/**
 * A-vs-B compare view (RFC discussion #2 point 3): "two nights ago BLIS vX, tonight vY — what
 * changed?". Shows the per-metric Δ over the points BOTH runs scored (strict intersection), as an
 * EXPLICIT user-chosen comparison — distinct from the implicit vs-previous delta that was removed.
 *
 * Δ = newer − older on each ERROR metric (MAPE / shape, TTFT / TPOT), whichever rail slot each run
 * was picked in: the two runs are ordered by snapshot date. Lower error is better, so Δ < 0 means
 * the newer run is MORE accurate → green; Δ > 0 means it regressed → red (#5). Ordering by date
 * rather than by slot is what keeps that meaning stable: with Δ = B − A, the default (A = latest)
 * showed a regression of the newer release in green.
 *
 * The single-run Overview, SummaryTable and PointsTable are untouched; this is a parallel view.
 */
import { useMemo } from 'react'
import { aggregate, flattenPoints, intersectByKey, type FlatPoint } from '../aggregate'
import { buildRows, type RenderRow } from '../tree'
import { formatSignedDelta, formatCount } from '../format'
import { Term } from './Term'
import type { Metric, Summary, TierKey } from '../types'

interface Props {
  a: Summary
  b: Summary
  tier: TierKey
}

/** One signed, sign-coloured Δ (percentage points). Negative = improved (green), positive = red. */
function DeltaCell({ v }: { v: number | null }) {
  const cls = v == null ? 'd-zero' : v < 0 ? 'd-better' : v > 0 ? 'd-worse' : 'd-zero'
  const title = v == null || v === 0 ? undefined : v < 0 ? 'improved: lower error in the newer run' : 'regressed: higher error in the newer run'
  return <span className={`num ${cls}`} title={title}>{formatSignedDelta(v)}</span>
}

/** newer − older, guarding nulls (if either side is null the Δ is undefined → null → em dash). */
function delta(aVal: number | null, bVal: number | null): number | null {
  if (aVal == null || bVal == null) return null
  return bVal - aVal
}

/** The two runs, older first: snapshot ids lead with their date, so they sort chronologically. */
function chronological(a: Summary, b: Summary): [Summary, Summary] {
  return a.snapshot_id <= b.snapshot_id ? [a, b] : [b, a]
}

export function Compare({ a: slotA, b: slotB, tier }: Props) {
  const [a, b] = useMemo(() => chronological(slotA, slotB), [slotA, slotB])
  // Strict intersection: only points scored by BOTH runs, aligned by cross-snapshot point key.
  const { aShared, bShared, shared, onlyA, onlyB } = useMemo(() => {
    const { pairs, onlyA, onlyB } = intersectByKey(flattenPoints(a), flattenPoints(b))
    return {
      aShared: pairs.map((p) => p.a),
      bShared: pairs.map((p) => p.b),
      shared: pairs.length,
      onlyA,
      onlyB,
    }
  }, [a, b])

  // Effective tier: like the Overview, the default measured_or_resolved falls back to "all" when the
  // shared set has zero measured·resolved points (the direct path leaves settings resolved → every
  // point lands in "all"), so the Δ table isn't entirely em dashes. An explicit tier click is honoured.
  const tierFellBack =
    tier === 'measured_or_resolved' &&
    aShared.length > 0 &&
    aShared.filter((p) => p.tier === 'measured_or_resolved').length === 0
  const effectiveTier: TierKey = tierFellBack ? 'all' : tier

  // Overall Δ headline (issue #17): the net "did it change?" number, POOLED over every shared
  // point — aggregate() on the full shared set, NOT the mean of the per-model rows below. Pooling
  // weights each point once; a row-mean would give a 20-point model the same weight as a 200-point
  // one and can flip sign (Simpson's paradox). This also keeps the headline equal to
  // Overview(newer) − Overview(older) on the shared set, since the Overview uses the same aggregate().
  const overall = useMemo(() => {
    const oa = aggregate(aShared, effectiveTier)
    const ob = aggregate(bShared, effectiveTier)
    return {
      mapeTtft: delta(oa.mape.ttft, ob.mape.ttft),
      shapeTtft: delta(oa.shape.ttft, ob.shape.ttft),
      mapeTpot: delta(oa.mape.tpot, ob.mape.tpot),
      shapeTpot: delta(oa.shape.tpot, ob.shape.tpot),
    }
  }, [aShared, bShared, effectiveTier])

  // Build both trees over the SAME shared point set → identical structure/ids, so we can zip by id.
  // Everything is expanded so the full drill-down of what changed is visible at once.
  const expanded = useMemo(() => allNodeIds(aShared), [aShared])
  const aRows = useMemo(() => buildRows(aShared, expanded), [aShared, expanded])
  const bRows = useMemo(() => buildRows(bShared, expanded), [bShared, expanded])
  const bById = useMemo(() => new Map(bRows.map((r) => [r.id, r])), [bRows])

  const metricVal = (row: RenderRow | undefined, kind: 'mape' | 'shape', m: Metric): number | null => {
    if (!row) return null
    const blk = row.metrics[effectiveTier]
    return blk[kind][m]
  }

  const idA = a.snapshot_id
  const idB = b.snapshot_id
  const blisA = a.provenance?.blis?.release ?? '?'
  const blisB = b.provenance?.blis?.release ?? '?'
  // Which rail slot each run was picked in, so the header's tags match the rail's A/B tags even
  // though the Δ is ordered by date rather than by slot.
  const slotOfA = a === slotA ? 'A' : 'B'
  const slotOfB = slotOfA === 'A' ? 'B' : 'A'
  const SlotTag = ({ slot }: { slot: 'A' | 'B' }) => (
    <span className={`cmp-tag ${slot === 'A' ? 'cmp-a' : 'cmp-b'}`}>{slot}</span>
  )

  return (
    <>
      <h2 className="viewhead">
        Compare runs — <Term name="diff">Δ accuracy (newer − older)</Term>
      </h2>
      <div className="cmp-head">
        <div className="cmp-run">
          <SlotTag slot={slotOfA} /> <span className="cmp-age">older</span> <b>{idA.slice(0, 10)}</b> · {blisA}
        </div>
        <div className="cmp-arrow">→</div>
        <div className="cmp-run">
          <SlotTag slot={slotOfB} /> <span className="cmp-age">newer</span> <b>{idB.slice(0, 10)}</b> · {blisB}
        </div>
        <div className="cmp-note">
          Δ = newer − older on each error metric over the <b>{formatCount(shared)}</b> points scored by
          both runs. <span className="d-better">green</span> = the newer run is more accurate (lower
          error) · <span className="d-worse">red</span> = the newer run regressed. Runs are ordered by
          date, so swapping them in the rail doesn't change the meaning.
          {(onlyA > 0 || onlyB > 0) && (
            <span className="cmp-cov">
              {' '}
              (coverage: {formatCount(onlyA)} only in the older run, {formatCount(onlyB)} only in the newer — excluded)
            </span>
          )}
          {tierFellBack && <span className="cmp-cov"> · no measured·resolved points — showing the all tier</span>}
        </div>
      </div>

      {shared === 0 ? (
        <div className="pts-empty">These two runs share no scored points — nothing to compare.</div>
      ) : (
        <>
        <div className="cmp-overall" role="group" aria-label="Overall delta across all shared points">
          <div className="cmp-overall-title">
            Overall Δ <span className="cmp-overall-sub">· point-weighted over all {formatCount(shared)} shared points</span>
          </div>
          <div className="cmp-overall-grid">
            <div className="cmp-overall-cell">
              <span className="cmp-overall-lbl">Δ TTFT mape</span>
              <DeltaCell v={overall.mapeTtft} />
            </div>
            <div className="cmp-overall-cell">
              <span className="cmp-overall-lbl">Δ TTFT shape</span>
              <DeltaCell v={overall.shapeTtft} />
            </div>
            <div className="cmp-overall-cell">
              <span className="cmp-overall-lbl">Δ TPOT mape</span>
              <DeltaCell v={overall.mapeTpot} />
            </div>
            <div className="cmp-overall-cell">
              <span className="cmp-overall-lbl">Δ TPOT shape</span>
              <DeltaCell v={overall.shapeTpot} />
            </div>
          </div>
        </div>
        <div className="tscroll">
          <table className="readout cmp">
            <thead>
              <tr className="grp">
                <th rowSpan={2} style={{ verticalAlign: 'bottom' }}>
                  Model / workload / GPU / topology
                </th>
                <th className="sep" colSpan={2}>
                  Δ mean TTFT
                </th>
                <th className="sep" colSpan={2}>
                  Δ mean TPOT
                </th>
              </tr>
              <tr className="col">
                <th className="sep">mape</th>
                <th>shape</th>
                <th className="sep">mape</th>
                <th>shape</th>
              </tr>
            </thead>
            <tbody>
              {aRows.map((row) => {
                const bRow = bById.get(row.id)
                return (
                  <tr key={row.id} className={`r${row.depth}`}>
                    <td className="name" style={{ paddingLeft: row.depth > 0 ? row.depth * 18 + 10 : undefined }}>
                      {row.level === 'model' ? <b className="name">{row.label}</b> : row.label}
                      {row.facet && <span className="facet">{row.facet}</span>}
                    </td>
                    <td className="sep">
                      <DeltaCell v={delta(metricVal(row, 'mape', 'ttft'), metricVal(bRow, 'mape', 'ttft'))} />
                    </td>
                    <td>
                      <DeltaCell v={delta(metricVal(row, 'shape', 'ttft'), metricVal(bRow, 'shape', 'ttft'))} />
                    </td>
                    <td className="sep">
                      <DeltaCell v={delta(metricVal(row, 'mape', 'tpot'), metricVal(bRow, 'mape', 'tpot'))} />
                    </td>
                    <td>
                      <DeltaCell v={delta(metricVal(row, 'shape', 'tpot'), metricVal(bRow, 'shape', 'tpot'))} />
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
        </>
      )}
      <div className="gate-legend">
        Δ in percentage points. A point counts only if BOTH runs scored it; coverage-only points are
        excluded from every Δ. The overall Δ is point-weighted over all shared points, so it need not
        equal the average of the per-model rows. Pick a different second run (or "none") in the rail.
      </div>
    </>
  )
}

/** Every node id the drill-down would produce for a point set — so the compare tree is fully open. */
function allNodeIds(points: FlatPoint[]): Set<string> {
  const ids = new Set<string>()
  for (const p of points) {
    const m = `m:${p.model}`
    const w = `${m}|w:${p.workloadLabel}`
    const g = `${w}|g:${p.gpu}`
    ids.add(m)
    ids.add(w)
    ids.add(g)
  }
  return ids
}
