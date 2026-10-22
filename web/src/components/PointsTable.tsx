/**
 * Table 2 — the points table for the selected topology row (measured vs predicted vs error %
 * per concurrency), the leaf view from the mockup. Absolute units in ms (signedprobe emits µs;
 * the orchestrator converts). A missing value renders an em dash, never NaN/blank (RFC B1).
 */
import { formatMs, formatSignedPct, formatVersion } from '../format'
import { Term } from './Term'
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
    // Colour the error by sign so over- vs under-prediction reads at a glance: positive =
    // BLIS predicted high (red), negative = predicted low (green). A null/zero stays neutral.
    const sign = v == null ? 'zero' : v > 0 ? 'pos' : v < 0 ? 'neg' : 'zero'
    return <span className={`num err-${sign}`}>{text}</span>
  }
  return <>{text}</>
}

export function PointsTable({ points, title, selMissing = false }: Props) {
  // Sort by concurrency, then group repeats by their vLLM version so the per-version rows read
  // in order. The version is where the repeated measured values come from (same deployment,
  // different vLLM build), so it earns its own column here.
  const sorted = [...points].sort(
    (a, b) => a.concurrency - b.concurrency || (a.engineVersion ?? '').localeCompare(b.engineVersion ?? ''),
  )
  // Surface why shape is absent for this sweep, if the scorer recorded a reason — previously
  // shapeReason was carried on every point but never shown (PR #3 review UI-c).
  const shapeReason = sorted.find((p) => p.shapeReason)?.shapeReason ?? null
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
          Each value is a per-run <b>arithmetic mean over the benchmark's requests</b> (vLLM
          <span className="mono"> calculate_metrics</span>): mean TTFT over all main-phase requests;
          mean TPOT = mean of (latency − TTFT) ⁄ (output_len − 1) over requests with &gt;1 output token.
          Not a median or tail — p99 is out of scope for v0.1.0. Measured means come from the
          InferenceX dump; predicted means from BLIS replaying the same requests, same definition.
          Repeated rows at one concurrency are the same deployment measured on different vLLM builds.
        </p>
      )}
    </>
  )
}
