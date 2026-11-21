/**
 * The sources page: one card per anchor source (InferenceX with its vLLM and SGLang lanes apart, configiq), each with its funnel,
 * its scored count and the reason of every unit not scored; the training-only sources as labelled training diagnostics, never
 * accuracy; and a loud note where ledger.yaml disagrees with design D9. The numbers are the published funnel.json's.
 */
import { formatCount } from '../format'
import { unscoredReasons, type Funnel, type FunnelDoc, type FunnelLane, type TrainingFunnel } from '../sources'

const STAGES: [keyof FunnelLane['stages'], string][] = [
  ['rows_held', 'rows held'],
  ['units', 'anchor units'],
  ['in_scope', 'in scope'],
  ['recoverable', 'recoverable (a floor)'],
  ['scored', 'scored'],
]

function StageTable({ lane }: { lane: Pick<FunnelLane, 'stages' | 'scored_by_grade'> }) {
  return (
    <table className="slices">
      <thead>
        <tr>
          <th>Stage</th>
          <th className="num">Units</th>
        </tr>
      </thead>
      <tbody>
        {STAGES.map(([k, label]) => (
          <tr key={k}>
            <td>{label}</td>
            <td className="num">{lane.stages[k] == null ? 'not probed' : formatCount(lane.stages[k] as number)}</td>
          </tr>
        ))}
        {Object.entries(lane.scored_by_grade).map(([g, n]) => (
          <tr key={g}>
            <td>{`scored ${g}`}</td>
            <td className="num">{formatCount(n)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function Reasons({ lane }: { lane: Parameters<typeof unscoredReasons>[0] }) {
  const rows = unscoredReasons(lane)
  if (rows.length === 0) return <p className="stat-hint">Every in-scope unit is scored.</p>
  return (
    <table className="slices">
      <thead>
        <tr>
          <th>Not scored</th>
          <th>Reason</th>
          <th className="num">Units</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r) => (
          <tr key={`${r.part}/${r.reason}`}>
            <td>{r.part}</td>
            <td>
              <code>{r.reason}</code>
            </td>
            <td className="num">{formatCount(r.units)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function SourceCard({ f }: { f: Funnel }) {
  const s = f.stages
  const lanes = Object.entries(f.lanes ?? {})
  return (
    <section className="classcard" id={`source-${f.source}`} aria-labelledby={`source-${f.source}-h`}>
      <h2 className="sectitle" id={`source-${f.source}-h`}>
        {f.source}
        <span className="pill classtag"> anchor source</span>
      </h2>
      <p className="context">{`Anchor rule: ${f.anchor_rule}.`}</p>
      <div className="stats">
        <div className="stat">
          <div className="stat-value">{formatCount(s.scored)}</div>
          <div className="stat-label">scored</div>
          <div className="stat-hint">{`of ${formatCount(s.in_scope)} in-scope anchor units (${formatCount(s.units)} anchor units)`}</div>
        </div>
        {f.provisional.units > 0 ? (
          <div className="stat">
            <div className="stat-value">{formatCount(f.provisional.units)}</div>
            <div className="stat-label">provisional</div>
            <div className="stat-hint">capped at G3, outside the scored count</div>
          </div>
        ) : null}
      </div>
      {Object.keys(f.not_anchor).length > 0 ? (
        <p className="stat-hint">{`Units outside the anchors: ${Object.entries(f.not_anchor).map(([k, v]) => `${k.replace(/_/g, ' ')} ${formatCount(v)}`).join(', ')}.`}</p>
      ) : null}
      <StageTable lane={f} />
      <Reasons lane={f} />
      {lanes.length > 0 ? (
        <>
          <h3 className="subtitle">By engine lane</h3>
          {lanes.map(([name, l]) => (
            <div key={name} className="lane" id={`source-${f.source}-lane-${name}`}>
              <h4>{`${f.source}, ${name} lane`}</h4>
              <p className="stat-hint">{`${formatCount(l.stages.scored)} scored of ${formatCount(l.stages.in_scope)} in scope (${formatCount(l.stages.units)} units)`}</p>
              <Reasons lane={l} />
            </div>
          ))}
        </>
      ) : null}
    </section>
  )
}

function TrainingCard({ t }: { t: TrainingFunnel }) {
  return (
    <section className="classcard kind-provisional" id={`training-${t.source}`}>
      <h3 className="sectitle">
        {t.source}
        <span className="pill classtag"> training only</span>
      </h3>
      <p className="context">{`${t.label}. ${formatCount(t.stages.units)} units from ${formatCount(t.stages.rows_held)} rows. No accuracy is reported for this source.`}</p>
    </section>
  )
}

export function Sources({ doc, error }: { doc: FunnelDoc | null; error: string | null }) {
  const cp = doc?.cut_points
  return (
    <div className="classes">
      <h2 className="viewhead">Anchor sources</h2>
      <p className="context">
        Accuracy is published on anchor units only. Each anchor source is counted on its own, with the reason for every unit not
        scored; the training-only sources are shown as training diagnostics and never as accuracy.
      </p>
      {error ? (
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
          {cp && cp.discrepancies.length > 0 ? (
            <div className="viewerror" role="alert">
              <h3>ledger.yaml disagrees with design D9</h3>
              <ul>
                {cp.discrepancies.map((d) => (
                  <li key={d.code + d.source}>
                    <strong>{d.source}</strong>: {d.text}
                  </li>
                ))}
              </ul>
            </div>
          ) : cp && !cp.checked ? (
            <p className="stat-hint">ledger.yaml was not checked against design D9 in this run.</p>
          ) : null}
          {Object.values(doc.funnels).map((f) => (
            <SourceCard key={f.source} f={f} />
          ))}
          {Object.keys(doc.training).length > 0 ? (
            <>
              <h2 className="viewhead">Training-only sources</h2>
              {Object.values(doc.training).map((t) => (
                <TrainingCard key={t.source} t={t} />
              ))}
            </>
          ) : null}
        </>
      )}
    </div>
  )
}
