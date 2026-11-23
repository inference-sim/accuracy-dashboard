/**
 * Accuracy by slice (design COV-13): the scored points cut by any recorded attribute. Each slice
 * shows its point count, role-key count and coverage beside its accuracy; a slice over fewer
 * than the minimum role keys shows the count in the accuracy's place and still lists its units.
 */
import { formatCount, formatFigure } from '../format'
import { TOO_FEW } from '../types'
import { sliceAttr, sliceBy, SLICE_ATTRS, UNRECORDED } from '../slice'
import type { FlatPoint } from '../aggregate'

interface Props {
  points: FlatPoint[]
  by: string | null
  sv: string | null
  min: number
  notScored: { hardware?: string }[]
  onBy: (by: string | null) => void
  onSv: (sv: string | null) => void
}

export function Slices({ points, by, sv, min, notScored, onBy, onSv }: Props) {
  const rows = by ? sliceBy(points, by, min, notScored) : []
  return (
    <section className="slices" aria-label="Accuracy by slice">
      <h2 className="sectitle">Accuracy by slice</h2>
      <div className="chips">
        <label className="flt">
          Slice by{' '}
          <select value={by ?? ''} onChange={(e) => onBy(e.target.value || null)}>
            <option value="">choose an attribute</option>
            {SLICE_ATTRS.map((a) => (
              <option key={a.id} value={a.id}>
                {a.label}
              </option>
            ))}
          </select>
        </label>
        <span className="disabled-note">
          not recorded on a point yet: {UNRECORDED.map((u) => u.label).join(', ')}
        </span>
      </div>
      <p className="pts-note">
        No accuracy is shown over fewer than {min} role keys, here or anywhere on the page. A role key is one
        deployment under one benchmark type; ten points from two role keys are two deployments. The count
        is shown in the accuracy's place, and the slice's points stay listed.
      </p>
      {by && (
        <div className="tscroll">
          <table className="readout slices-tbl" aria-label={`accuracy by ${sliceAttr(by)?.label ?? by}`}>
            <thead>
              <tr className="col">
                <th>{sliceAttr(by)?.label}</th>
                <th>points</th>
                <th>role keys</th>
                <th>coverage</th>
                <th>TTFT error</th>
                <th>TPOT error</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.value} className={sv === r.value ? 'on' : undefined}>
                  <td className="mono">
                    <a href={`#slice-${r.value}`} onClick={(e) => { e.preventDefault(); onSv(sv === r.value ? null : r.value) }}>
                      {r.value}
                    </a>
                    {!r.shown && (
                      <details className="slice-units">
                        <summary>{r.reason}</summary>
                        <span className="mono">{r.units.join(', ')}</span>
                      </details>
                    )}
                  </td>
                  <td>{formatCount(r.points)}</td>
                  <td>{formatCount(r.roleKeys)}</td>
                  <td>{r.coverage ? `${formatCount(r.coverage.scored)} of ${formatCount(r.coverage.total)}` : '—'}</td>
                  <td>{r.shown ? formatFigure(r.ttft) : `${TOO_FEW} (${formatCount(r.roleKeys)} role keys)`}</td>
                  <td>{r.shown ? formatFigure(r.tpot) : `${TOO_FEW} (${formatCount(r.roleKeys)} role keys)`}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {by && sv && (
        <p className="pts-note slice-drill">
          Drilled into <b>{sliceAttr(by)?.label} = {sv}</b>: the table below holds this slice only.{' '}
          <a href="#clear" onClick={(e) => { e.preventDefault(); onSv(null) }}>show all slices</a>
        </p>
      )}
    </section>
  )
}
