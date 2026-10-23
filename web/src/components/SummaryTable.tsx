/**
 * Table 1 — the summary drill-down (model → workload → GPU → topology), as the approved
 * mockup lays it out. The overall numbers are the Headline cards above the table (#23), so the
 * table starts at the models. Columns are mean TTFT/TPOT:
 * MAPE & shape, one value per cell (no delta — the A-vs-B Δ is a separate Compare view). Selecting a topology row
 * populates the points table (handled by the parent). Numbers are recomputed client-side from
 * the visible points, so a filter never shows a stale aggregate (RFC B3).
 */
import { formatPct } from '../format'
import { Term } from './Term'
import { ProvenanceBody } from './Provenance'
import type { RenderRow } from '../tree'
import type { SortKey, SortSpec } from '../sort'
import type { MetricBlockPair, TierKey } from '../types'

interface Props {
  rows: RenderRow[]
  tier: TierKey
  sort: SortSpec | null
  onSort: (key: SortKey) => void
  selectedId: string | null
  onToggle: (id: string) => void
  onSelect: (sweepKey: string, id: string) => void
  expanded: Set<string>
}

function Num({ v }: { v: number | null }) {
  return <span className="num">{formatPct(v)}</span>
}

function HeaderButton({
  label,
  k,
  sort,
  onSort,
}: {
  label: string
  k: SortKey
  sort: SortSpec | null
  onSort: (k: SortKey) => void
}) {
  const active = sort?.key === k
  const arrow = active ? (sort!.dir === 1 ? '▲' : '▼') : ''
  return (
    <button
      type="button"
      className="sortbtn"
      aria-sort={active ? (sort!.dir === 1 ? 'ascending' : 'descending') : undefined}
      onClick={() => onSort(k)}
    >
      {label} {arrow && <span className="arrow">{arrow}</span>}
    </button>
  )
}

export function SummaryTable(props: Props) {
  const { rows, tier, sort, onSort, selectedId } = props
  const tb = (b: MetricBlockPair) => b[tier]

  return (
    <div className="tscroll">
      <table className="readout">
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
            {/* mape/shape live inside a sortable <button>; a focusable Term CANNOT nest in a button,
                so the term affordance is a sibling info marker (<Term> as a superscript ⓘ) next to
                the sort button, not wrapping its label. */}
            <th className="sep">
              <HeaderButton label="error" k="ttft_mape" sort={sort} onSort={onSort} />
              <Term name="mape"><sup className="term-info" aria-label="what is mape">ⓘ</sup></Term>
            </th>
            <th>
              <HeaderButton label="trend" k="ttft_shape" sort={sort} onSort={onSort} />
              <Term name="shape"><sup className="term-info" aria-label="what is shape">ⓘ</sup></Term>
            </th>
            <th className="sep">
              <HeaderButton label="error" k="tpot_mape" sort={sort} onSort={onSort} />
              <Term name="mape"><sup className="term-info" aria-label="what is mape">ⓘ</sup></Term>
            </th>
            <th>
              <HeaderButton label="trend" k="tpot_shape" sort={sort} onSort={onSort} />
              <Term name="shape"><sup className="term-info" aria-label="what is shape">ⓘ</sup></Term>
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const b = tb(row.metrics)
            const isSelected = row.level === 'topology' && selectedId === row.id
            const canExpand = row.level !== 'topology'
            const caretOpen = props.expanded.has(row.id)
            const caret = row.level === 'topology' ? '▸' : caretOpen ? '▾' : '▸'
            const onRowClick = () => {
              if (row.level === 'topology' && row.sweepKey) props.onSelect(row.sweepKey, row.id)
              else props.onToggle(row.id)
            }
            return (
              <tr
                key={row.id}
                className={`r${row.depth}${row.level === 'topology' ? '' : ' selrow'}${isSelected ? ' sel' : ''}`}
                onClick={onRowClick}
              >
                <td className="name" style={{ paddingLeft: row.depth > 0 ? row.depth * 18 + 10 : undefined }}>
                  <span className={`caret${canExpand ? ' clk' : ''}`}>{caret}</span>
                  {row.level === 'model' ? <b className="name">{row.label}</b> : row.label}
                  {row.facet && <span className="facet">{row.facet}</span>}
                  {row.fidelity && (
                    // stopPropagation: opening the tooltip by click/tap must not select the row
                    <span className="prov-inrow" onClick={(e) => e.stopPropagation()}>
                      <Term
                        content={
                          <>
                            <span className="prov-h">
                              {row.pointCount} point{row.pointCount === 1 ? '' : 's'}
                              {row.approxCount ? ` · ${row.approxCount} approximate` : ' · all exact'}
                            </span>
                            <ProvenanceBody fidelity={row.fidelity} />
                          </>
                        }
                        popClass="term-pop-wide"
                        ariaLabel="provenance for this deployment"
                      >
                        <span className={`prov-mark${row.approxCount ? ' approx' : ''}`} aria-hidden="true">
                          {row.approxCount ? '≈' : 'ⓘ'}
                        </span>
                      </Term>
                    </span>
                  )}
                </td>
                <td className="sep">
                  <Num v={b.mape.ttft} />
                </td>
                <td>
                  <Num v={b.shape.ttft} />
                </td>
                <td className="sep">
                  <Num v={b.mape.tpot} />
                </td>
                <td>
                  <Num v={b.shape.tpot} />
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
