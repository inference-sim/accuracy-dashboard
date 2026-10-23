/**
 * Table 2 — the points table for the selected topology row (measured vs predicted vs error %
 * per concurrency), the leaf view from the mockup. Absolute units in ms (signedprobe emits µs;
 * the orchestrator converts). A missing value renders an em dash, never NaN/blank (RFC B1).
 */
import { formatMs, formatSignedPct, formatVersion } from '../format'
import { Term } from './Term'
import { ProvenanceTip } from './Provenance'
import type { FlatPoint } from '../aggregate'

interface Props {
  points: FlatPoint[]
  title: string
  /** true when a row IS selected (?sel=) but resolves to zero points in this snapshot/filter —
   *  shown distinctly from the "nothing selected yet" prompt (PR #3 review UI-c). */
  selMissing?: boolean
}

// Both TTFT and TPOT render at a fixed 2 decimals — the measured/predicted values carry sub-ms
// precision, and a uniform precision keeps every cell (and both columns) directly comparable.
const MS_DIGITS = 2

function Cell({ v, kind }: { v: number | null; kind: 'ms' | 'err' }) {
  const text = kind === 'ms' ? formatMs(v, MS_DIGITS) : formatSignedPct(v)
  if (kind === 'err') {
    // The sign is a DIRECTION, not a judgement: predicting 15% low is as far off as 15% high, so
    // both share one neutral colour and an arrow says which way (PR #26 review). Green/red stays
    // only in the compare view, where lower error than the other run really is better.
    const dir = v == null || v === 0 ? null : v > 0 ? 'over' : 'under'
    return (
      <span className="num err" title={dir ? `BLIS predicted ${dir === 'over' ? 'higher' : 'lower'} than measured` : undefined}>
        {dir && <span className="err-dir" aria-hidden="true">{dir === 'over' ? '▲' : '▼'}</span>}
        {text}
      </span>
    )
  }
  return <>{text}</>
}

export function PointsTable({ points, title, selMissing = false }: Props) {
  // Sort by concurrency, then group repeats by their vLLM version so the per-version rows read
  // in order. The version is where the repeated measured values come from (same deployment,
  // different vLLM build), so it earns its own column here.
  const sorted = [...points].sort(
    (a, b) =>
      a.concurrency - b.concurrency ||
      (a.engineVersion ?? '').localeCompare(b.engineVersion ?? '') ||
      (a.measuredDate ?? '').localeCompare(b.measuredDate ?? ''),
  )
  // v2 snapshots date each measurement and carry its provenance; v1 has neither, and then the
  // table is exactly as before.
  const dated = sorted.some((p) => p.measuredDate)
  const withProv = sorted.some((p) => p.fidelity)
  // Surface why shape is absent for this sweep, if the scorer recorded a reason — previously
  // shapeReason was carried on every point but never shown (PR #3 review UI-c).
  const shapeReason = sorted.find((p) => p.shapeReason)?.shapeReason ?? null
  // Nothing picked yet: one quiet hint instead of an empty boxed panel on first view (#23).
  if (sorted.length === 0 && !selMissing) {
    return (
      <p className="pts-hint">
        Expand a model above and pick a deployment to see each measurement next to its prediction.
      </p>
    )
  }
  return (
    <>
      <div className="tbl-title" style={{ marginTop: 26 }}>
        {title}{' '}
        <span className="facet">measured vs predicted per concurrency · vLLM build · absolute units · error %</span>
      </div>
      <div className="tscroll">
        {sorted.length === 0 ? (
          selMissing ? (
            <div className="pts-empty">
              That topology isn’t in this snapshot (it may have aged out, differ by run, or be hidden
              by the current tier / vLLM-version filter). Pick a row below, or clear the filters.
            </div>
          ) : (
            <div className="pts-empty">Expand a model above and pick a deployment to see each measurement next to its prediction.</div>
          )
        ) : (
          <table className="readout pts">
            <thead>
              <tr className="grp">
                <th rowSpan={2} style={{ verticalAlign: 'bottom' }}>
                  Concurrency
                </th>
                {/* keep-case: the brand is vLLM, not VLLM — opt this header out of the grp uppercase rule */}
                <th rowSpan={2} className="keepcase" style={{ verticalAlign: 'bottom' }}>
                  vLLM
                </th>
                {dated && (
                  <th rowSpan={2} style={{ verticalAlign: 'bottom' }}>
                    Measured
                  </th>
                )}
                {withProv && (
                  <th rowSpan={2} style={{ verticalAlign: 'bottom' }}>
                    <Term name="provenance" />
                  </th>
                )}
                <th className="sep" colSpan={3}>
                  mean <Term name="ttft" /> (ms)
                </th>
                <th className="sep" colSpan={3}>
                  mean <Term name="tpot" /> (ms)
                </th>
              </tr>
              <tr className="col">
                <th className="sep">meas</th>
                <th>pred</th>
                <th>err</th>
                <th className="sep">meas</th>
                <th>pred</th>
                <th>err</th>
              </tr>
            </thead>
            <tbody>
              {sorted.map((p, i) => (
                // InferenceX carries repeat benchmark runs at the SAME concurrency (different
                // vLLM builds), so concurrency alone is not a unique key — index disambiguates.
                <tr key={`${p.concurrency}-${i}`}>
                  <td className="mono">{p.concurrency}</td>
                  <td className="mono">
                    {p.engineVersion ? <span className="ver neutral">{formatVersion(p.engineVersion)}</span> : <span className="marker">—</span>}
                  </td>
                  {dated && <td className="mono">{p.measuredDate ?? <span className="marker">—</span>}</td>}
                  {withProv && (
                    <td className="prov-cell">
                      <ProvenanceTip fidelity={p.fidelity} measuredDate={p.measuredDate} />
                    </td>
                  )}
                  <td className="sep mono">
                    <Cell v={p.measTtftMs} kind="ms" />
                  </td>
                  <td className="mono">
                    <Cell v={p.predTtftMs} kind="ms" />
                  </td>
                  <td className="e">
                    <Cell v={p.errTtft} kind="err" />
                  </td>
                  <td className="sep mono">
                    <Cell v={p.measTpotMs} kind="ms" />
                  </td>
                  <td className="mono">
                    <Cell v={p.predTpotMs} kind="ms" />
                  </td>
                  <td className="e">
                    <Cell v={p.errTpot} kind="err" />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
      {shapeReason && (
        <p className="pts-note notscored-detail">
          <b>shape not scored:</b> {shapeReason}
        </p>
      )}
      {sorted.length > 0 && (
        <p className="pts-note">
          <b>▲</b> BLIS predicted higher than measured · <b>▼</b> lower. Both are equally off; the
          size of the number is what matters.
        </p>
      )}
      {sorted.length > 0 && (
        <p className="pts-note">
          Each value is a <b>mean over the run’s requests</b>: mean TTFT over every measured request, and
          mean TPOT = (latency − TTFT) ÷ (output tokens − 1), averaged over requests with more than one
          output token. Not a median or a tail percentile. Measured means come from InferenceX’s
          benchmark client; predicted means from BLIS replaying the same requests, computed the same way.
          Repeated rows at one concurrency are the same deployment measured on different vLLM builds
          {dated ? ' or dates' : ''}.
        </p>
      )}
    </>
  )
}
