/**
 * Table 1 — the summary drill-down (model → workload → GPU → topology), as the approved
 * mockup lays it out. A totals/headline row sits above the models with the
 * visible same-points Δ. Columns are mean TTFT/TPOT: MAPE & shape. Selecting a topology row
 * populates the points table (handled by the parent). Numbers are recomputed client-side from
 * the visible points, so a filter never shows a stale aggregate (RFC B3).
 */
import { formatDelta, formatPct } from '../format'
import type { RenderRow } from '../tree'
import type { SortKey, SortSpec } from '../sort'
import type { MetricBlockPair, SamePointsDelta, TierKey } from '../types'

interface Props {
  totals: MetricBlockPair
  totalsDelta: SamePointsDelta | null
  totalsPointCount: number
  rows: RenderRow[]
  tier: TierKey
  targetVllm: string
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

function VerBadge({ vllm, onTarget }: { vllm: string | null; onTarget: boolean | null }) {
  if (!vllm) return null
  return <span className={`ver${onTarget === false ? ' off' : ''}`}>v{vllm.replace(/^v/, '')}</span>
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
  const { totals, totalsDelta, totalsPointCount, rows, tier, targetVllm, sort, onSort, selectedId } = props
  const tb = (b: MetricBlockPair) => b[tier]
  const t = tb(totals)
  const delta = totalsDelta ? formatDelta(totalsDelta.tpot_mape) : null

  return (
    <div className="tscroll">
      <table className="readout">
        <thead>
          <tr className="grp">
            <th rowSpan={2} style={{ verticalAlign: 'bottom' }}>
              Model / workload / GPU / topology
            </th>
            <th rowSpan={2} style={{ verticalAlign: 'bottom' }}>
              vLLM
            </th>
            <th className="sep" colSpan={2}>
              TTFT (mean)
            </th>
            <th className="sep" colSpan={2}>
              TPOT (mean)
            </th>
          </tr>
          <tr className="col">
            <th className="sep">
              <HeaderButton label="mape" k="ttft_mape" sort={sort} onSort={onSort} />
            </th>
            <th>
              <HeaderButton label="shape" k="ttft_shape" sort={sort} onSort={onSort} />
            </th>
            <th className="sep">
              <HeaderButton label="mape" k="tpot_mape" sort={sort} onSort={onSort} />
            </th>
            <th>
              <HeaderButton label="shape" k="tpot_shape" sort={sort} onSort={onSort} />
            </th>
          </tr>
        </thead>
        <tbody>
          {/* totals / headline row */}
          <tr className="r0 totals">
            <td className="name">
              <b>ALL MODELS</b>
              <span className="facet">
                headline · {props.tier === 'all' ? 'all versions' : `on-target v${targetVllm}`} · {totalsPointCount} pts
              </span>
            </td>
            <td>
              <VerBadge vllm={targetVllm} onTarget={true} />
            </td>
            <td className="sep">
              <Num v={t.mape.ttft} />
              {totalsDelta && formatDelta(totalsDelta.ttft_mape) && (
                <span className={`delta ${formatDelta(totalsDelta.ttft_mape)!.dir}`}>
                  {formatDelta(totalsDelta.ttft_mape)!.text}
                </span>
              )}
            </td>
            <td>
              <Num v={t.shape.ttft} />
            </td>
            <td className="sep">
              <Num v={t.mape.tpot} />
              {delta && <span className={`delta ${delta.dir}`}>{delta.text}</span>}
            </td>
            <td>
              <Num v={t.shape.tpot} />
            </td>
          </tr>

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
                  {isSelected && <span className="facet">← selected</span>}
                </td>
                <td>
                  <VerBadge vllm={row.vllm} onTarget={row.onTarget} />
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
