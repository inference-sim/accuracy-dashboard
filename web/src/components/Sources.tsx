/**
 * The sources page: one table, a row per anchor source (InferenceX's vLLM and SGLang lanes follow it as their own rows), with
 * how many units it holds, how many are scored and why the rest are not. The rows come from funnel.json (sourceRows); the
 * columns are the COLUMNS list below, so a new column is one entry. A source with no units is still a row.
 */
import type { ReactNode } from 'react'
import { formatCount } from '../format'
import { sourceRows, unscoredReasons, type FunnelDoc, type SourceRow } from '../sources'

interface Column {
  key: string
  header: string
  num?: boolean
  cell: (r: SourceRow) => ReactNode
}

const notScored = (r: SourceRow) => unscoredReasons(r).reduce((n, x) => n + x.units, 0)

const COLUMNS: Column[] = [
  { key: 'source', header: 'Source', cell: (r) => (r.lane ? <span style={{ paddingLeft: 16 }}>{r.lane} engine</span> : r.source) },
  { key: 'role', header: 'Role', cell: (r) => r.role ?? '' },
  { key: 'units', header: 'Units', num: true, cell: (r) => formatCount(r.stages.units) },
  { key: 'in_scope', header: 'In scope', num: true, cell: (r) => formatCount(r.stages.in_scope) },
  { key: 'scored', header: 'Scored', num: true, cell: (r) => formatCount(r.stages.scored) },
  { key: 'not_scored', header: 'Not scored', num: true, cell: (r) => formatCount(notScored(r)) },
  { key: 'main_reason', header: 'Main reason not scored', cell: (r) => {
    const top = unscoredReasons(r)[0]
    return top ? <><code>{top.reason}</code> ({formatCount(top.units)})</> : 'none'
  } },
]

function Reasons({ rows }: { rows: SourceRow[] }) {
  const all = rows.flatMap((r) => unscoredReasons(r).map((x) => ({ ...x, where: r.lane ? `${r.source}, ${r.lane}` : r.source, id: r.id })))
  if (all.length === 0) return null
  return (
    <details className="about">
      <summary>All reasons units were not scored</summary>
      <div className="tscroll">
      <table className="readout sources-table">
        <thead>
          <tr>
            <th>Source</th>
            <th>Stage</th>
            <th>Reason</th>
            <th className="num">Units</th>
          </tr>
        </thead>
        <tbody>
          {all.map((x) => (
            <tr key={`${x.id}/${x.part}/${x.reason}`}>
              <td>{x.where}</td>
              <td>{x.part}</td>
              <td>
                <code>{x.reason}</code>
              </td>
              <td className="num">{formatCount(x.units)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      </div>
    </details>
  )
}

export function Sources({ doc, error, notPublished = false }: { doc: FunnelDoc | null; error: string | null; notPublished?: boolean }) {
  const rows = doc ? sourceRows(doc) : []
  return (
    <div className="classes">
      <h2 className="viewhead">Sources</h2>
      {error && notPublished ? (
        <p className="context" role="status">
          The per-source funnels are not published for this run yet. They are written by the baseline report, not by the nightly,
          so this page fills in when a baseline publishes them.
        </p>
      ) : error ? (
        <div className="viewerror" role="alert">
          <h3>Could not load the per-source funnels.</h3>
          <pre>
            <code>{error}</code>
          </pre>
        </div>
      ) : doc == null ? (
        <div className="loading">Loading the per-source funnels…</div>
      ) : (
        <>
          <div className="tscroll">
          <table className="readout sources-table">
            <thead>
              <tr>
                {COLUMNS.map((c) => (
                  <th key={c.key} className={c.num ? 'num' : undefined}>
                    {c.header}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id} className={r.lane ? 'lane' : 'src'}>
                  {COLUMNS.map((c) => (
                    <td key={c.key} className={c.num ? 'num' : undefined}>
                      {c.cell(r)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
          </div>
          <Reasons rows={rows} />
        </>
      )}
    </div>
  )
}
