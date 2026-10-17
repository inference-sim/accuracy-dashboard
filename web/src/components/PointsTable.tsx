/**
 * Table 2 — the points table for the selected topology row (measured vs predicted vs error %
 * per concurrency), the leaf view from the mockup. Absolute units in ms (signedprobe emits µs;
 * the orchestrator converts). A missing value renders an em dash, never NaN/blank (RFC B1).
 */
import { formatMs, formatSignedPct } from '../format'
import type { FlatPoint } from '../aggregate'

interface Props {
  points: FlatPoint[]
  title: string
  vllm: string | null
}

function Cell({ v, kind }: { v: number | null; kind: 'ms' | 'err' }) {
  const text = kind === 'ms' ? formatMs(v) : formatSignedPct(v)
  if (kind === 'err') return <span className="num">{text}</span>
  return <>{text}</>
}

export function PointsTable({ points, title, vllm }: Props) {
  const sorted = [...points].sort((a, b) => a.concurrency - b.concurrency)
  return (
    <>
      <div className="tbl-title" style={{ marginTop: 26 }}>
        {title}
        {vllm && <span className="ver neutral">v{vllm.replace(/^v/, '')}</span>}{' '}
        <span className="facet">measured vs predicted per concurrency, absolute units · error %</span>
      </div>
      <div className="tscroll">
        {sorted.length === 0 ? (
          <div className="pts-empty">Select a topology row in the summary table above to see its per-concurrency points.</div>
        ) : (
          <table className="readout pts">
            <thead>
              <tr className="grp">
                <th rowSpan={2} style={{ verticalAlign: 'bottom' }}>
                  conc
                </th>
                <th className="sep" colSpan={3}>
                  TTFT (ms)
                </th>
                <th className="sep" colSpan={3}>
                  TPOT (ms)
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
                // InferenceX carries repeat benchmark runs at the SAME concurrency, so
                // concurrency alone is not a unique key — index disambiguates the repeats.
                <tr key={`${p.concurrency}-${i}`}>
                  <td className="mono">{p.concurrency}</td>
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
    </>
  )
}
