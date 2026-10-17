/**
 * Table 1 — the summary drill-down (model → workload → GPU → topology), as the approved
 * mockup lays it out. A totals/headline row sits above the models with the
 * visible same-points Δ. Columns are mean TTFT/TPOT: MAPE & shape. Selecting a topology row
 * populates the points table (handled by the parent). Numbers are recomputed client-side from
 * the visible points, so a filter never shows a stale aggregate (RFC B3).
 */
import { formatPct, formatVersion } from '../format'
import type { RenderRow } from '../tree'
import type { SortKey, SortSpec } from '../sort'
import type { MetricBlockPair, TierKey } from '../types'

interface Props {
  totals: MetricBlockPair
  totalsPointCount: number
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

// The vLLM version facet for a row (no pass/fail colouring — a facet, not a verdict). A single
// version shows its badge; a row that pools several shows "N versions" rather than claiming one
// (so a model row spanning 8 builds never masquerades as one specific version).
function VerCell({ versions }: { versions: string[] }) {
  if (versions.length === 0) return null
  if (versions.length === 1) return <span className="ver neutral">{formatVersion(versions[0]!)}</span>
  return <span className="facet" title={versions.map(formatVersion).join(', ')}>{versions.length} versions</span>
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
  const { totals, totalsPointCount, rows, tier, sort, onSort, selectedId } = props
  const tb = (b: MetricBlockPair) => b[tier]
  const t = tb(totals)

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
              <span className="facet">headline · {totalsPointCount} pts</span>
            </td>
            {/* No vLLM badge on the totals row — it aggregates across versions (per-model rows carry the badge). */}
            <td />
            <td className="sep">
              <Num v={t.mape.ttft} />
            </td>
            <td>
              <Num v={t.shape.ttft} />
            </td>
            <td className="sep">
              <Num v={t.mape.tpot} />
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
                  <VerCell versions={row.versions} />
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
