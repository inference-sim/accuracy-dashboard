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
 * Lives on the "For BLIS developers" tab (#23): release-over-release change is for contributors,
 * not for a visitor asking "how accurate is BLIS?".
 */
import { useMemo, useState } from 'react'
import { aggregate, flattenPoints, intersectByKey } from '../aggregate'
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
  // Models start collapsed (#23): the verdict above answers "did it change?", and a reader opens
  // only the model they care about instead of scrolling past every deployment.
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set())
  const onToggle = (id: string) => {
    const next = new Set(expanded)
    if (next.has(id)) next.delete(id)
    else next.add(id)
    setExpanded(next)
  }
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
  // Which picker slot each run was chosen in, so the header's tags match the pickers' A/B tags
  // even though the Δ is ordered by date rather than by slot.
  const slotOfA = a === slotA ? 'A' : 'B'
  const slotOfB = slotOfA === 'A' ? 'B' : 'A'
  const SlotTag = ({ slot }: { slot: 'A' | 'B' }) => (
    <span className={`cmp-tag ${slot === 'A' ? 'cmp-a' : 'cmp-b'}`}>{slot}</span>
  )

  // A v1 snapshot (the db-dump pipeline) and a v2 one (the API ingest) identify points
  // differently and drew their settings from different sources, so a Δ between them would
  // mix two methods. Refused rather than shown (#30).
  const ingestA = a.provenance?.ingest ?? 'db-dump'
  const ingestB = b.provenance?.ingest ?? 'db-dump'
  if (ingestA !== ingestB) {
    return (
      <div className="pts-empty" role="note">
        These two runs came from different ingests ({ingestA === 'api' ? 'the InferenceX API' : 'the database dump'} and{' '}
        {ingestB === 'api' ? 'the InferenceX API' : 'the database dump'}), so their measurements aren’t comparable point
        for point. Pick two runs from the same ingest.
      </div>
    )
  }

  return (
    <>
      <div className="cmp-head">
        <div className="cmp-run">
          <SlotTag slot={slotOfA} /> <span className="cmp-age">older</span> <b>{blisA}</b> · {idA.slice(0, 10)}
        </div>
        <div className="cmp-arrow">→</div>
        <div className="cmp-run">
          <SlotTag slot={slotOfB} /> <span className="cmp-age">newer</span> <b>{blisB}</b> · {idB.slice(0, 10)}
        </div>
      </div>

      {shared === 0 ? (
        <div className="pts-empty">These two runs share no scored measurements, so there is nothing to compare.</div>
      ) : (
        <>
        <div className="cmp-overall" role="group" aria-label="Overall change across all shared measurements">
          <div className="cmp-overall-grid">
            <Verdict label="Time to first token" err={overall.mapeTtft} trend={overall.shapeTtft} />
            <Verdict label="Time per output token" err={overall.mapeTpot} trend={overall.shapeTpot} />
          </div>
          <p className="cmp-overall-sub">
            Change in average error, newer minus older, over the {formatCount(shared)} measurements
            scored by both runs. Lower error is better.
            {(onlyA > 0 || onlyB > 0) && (
              <>
                {' '}Comparing {formatCount(shared)} of {formatCount(shared + Math.max(onlyA, onlyB))} points:{' '}
                {formatCount(onlyA + onlyB)} measurements only one run scored are left out.
              </>
            )}
            {tierFellBack && <> Showing all measurements (none are {a.schema_version === 2 ? 'exact' : 'measured·resolved'} yet).</>}
          </p>
        </div>
        <h2 className="sectitle">By model</h2>
        <div className="tscroll">
          <table className="readout cmp">
            <thead>
              <tr className="grp">
                <th rowSpan={2} style={{ verticalAlign: 'bottom' }}>
                  Model
                </th>
                <th className="sep" colSpan={2}>
                  Mean time to first token
                </th>
                <th className="sep" colSpan={2}>
                  Mean time per output token
                </th>
              </tr>
              <tr className="col">
                <th className="sep"><Term name="mape" /></th>
                <th><Term name="shape" /></th>
                <th className="sep"><Term name="mape" /></th>
                <th><Term name="shape" /></th>
              </tr>
            </thead>
            <tbody>
              {aRows.map((row) => {
                const bRow = bById.get(row.id)
                const canExpand = row.level !== 'topology'
                const caret = canExpand && expanded.has(row.id) ? '▾' : '▸'
                return (
                  <tr
                    key={row.id}
                    className={`r${row.depth}${canExpand ? ' selrow' : ''}`}
                    onClick={canExpand ? () => onToggle(row.id) : undefined}
                  >
                    <td className="name" style={{ paddingLeft: row.depth > 0 ? row.depth * 18 + 10 : undefined }}>
                      {canExpand && <span className="caret clk">{caret}</span>}
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
        <div className="gate-legend">
          Percentage points, newer minus older. <span className="d-better">Green</span> = the newer run is
          more accurate, <span className="d-worse">red</span> = less accurate. Click a model to break it down.
        </div>
        </>
      )}
    </>
  )
}

/** The verdict for one metric, in words: how much the average error moved, and which way (#23). */
function Verdict({ label, err, trend }: { label: string; err: number | null; trend: number | null }) {
  const word = err == null || err === 0 ? 'no change' : err < 0 ? 'better' : 'worse'
  return (
    <div className="cmp-overall-cell">
      <span className="cmp-overall-lbl">{label}</span>
      <span>
        <DeltaCell v={err} /> <span className="cmp-unit">points</span>{' '}
        <span className={`cmp-word ${err == null || err === 0 ? 'd-zero' : err < 0 ? 'd-better' : 'd-worse'}`}>{word}</span>
      </span>
      <span className="cmp-trend">
        trend error <DeltaCell v={trend} />
      </span>
    </div>
  )
}
