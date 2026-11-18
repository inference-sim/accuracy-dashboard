/**
 * The classes page: one card per class of points (regular InferenceX, SGLang, reconstructed recipe, configiq), each with its own
 * counts, grade mix and accuracy by grade. Classes sit side by side and are never summed; a reconstructed or provisional class
 * carries its tag in its heading. The numbers are the published classes.json's, not recomputed here.
 */
import { formatCount, formatFigure, formatSignedPct } from '../format'
import {
  CLASS_GRADES,
  GRADED,
  kindTag,
  statsOf,
  type ClassEntry,
  type ClassFigure,
  type ClassStat,
  type ClassesDoc,
} from '../classes'

const STAT_LABEL: Record<ClassStat, string> = { ttft: 'TTFT', tpot: 'TPOT', itl: 'ITL' }
const GRADE_LABEL: Record<string, string> = {
  G1: 'exact',
  G2: 'estimated',
  G3: 'other release, same code',
  G4: 'other release or build',
  G5: 'not scored',
}

function FigureCell({ f }: { f: ClassFigure | undefined }) {
  if (!f) return <td className="num">—</td>
  return (
    <td className="num">
      {formatFigure(f.mape)}
      {typeof f.signed_median === 'number' ? <span className="stat-hint">{` · median ${formatSignedPct(f.signed_median)}`}</span> : null}
      <span className="stat-hint">{` · ${formatCount(f.n)} pt${f.n === 1 ? '' : 's'}`}</span>
    </td>
  )
}

function ClassCard({ c }: { c: ClassEntry }) {
  const tag = kindTag(c.kind)
  const stats = statsOf(c)
  const n = c.counts
  return (
    <section className={`classcard kind-${c.kind}`} id={`class-${c.id}`} aria-labelledby={`class-${c.id}-h`}>
      <h2 className="sectitle" id={`class-${c.id}-h`}>
        {c.label}
        {tag ? <span className="pill classtag"> {tag}</span> : null}
        {c.interim ? <span className="pill classtag interim"> interim</span> : null}
      </h2>
      <p className="context">{c.note}</p>
      <div className="stats">
        <div className="stat">
          <div className="stat-value">{formatCount(n.scored)}</div>
          <div className="stat-label">scored</div>
          <div className="stat-hint">of {formatCount(n.points)} points</div>
        </div>
        <div className="stat">
          <div className="stat-value">{formatCount(n.refused)}</div>
          <div className="stat-label">refused, by name</div>
          <div className="stat-hint">
            {formatCount(n.failed)} failed
            {n.withheld ? ` · ${formatCount(n.withheld)} withheld (test split)` : ''}
          </div>
        </div>
      </div>
      <table className="grades" aria-label={`${c.label}: points and accuracy by grade`}>
        <thead>
          <tr>
            <th scope="col">Grade</th>
            <th scope="col">Points</th>
            {stats.map((s) => (
              <th scope="col" key={s}>
                {STAT_LABEL[s]} error
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {CLASS_GRADES.map((g) => (
            <tr key={g}>
              <th scope="row">
                {g} <span className="stat-hint">{GRADE_LABEL[g]}</span>
              </th>
              <td className="num">{formatCount(c.grades[g])}</td>
              {stats.map((s) =>
                (GRADED as readonly string[]).includes(g) ? (
                  <FigureCell key={s} f={c.accuracy_by_grade[g]?.[s]} />
                ) : (
                  <td key={s} className="num">
                    —
                  </td>
                ),
              )}
            </tr>
          ))}
        </tbody>
      </table>
      {c.itl_streamed_in_chunks_left_out ? (
        <p className="context">
          ITL compares one token per chunk; {formatCount(c.itl_streamed_in_chunks_left_out)} scored points streamed several tokens per
          chunk and are left out of it.
        </p>
      ) : null}
      {c.engines && c.engines.length > 0 ? (
        <table className="readout classengines" aria-label="Points by framework">
          <thead>
            <tr>
              <th>Framework</th>
              <th>Points</th>
              <th>Graded</th>
            </tr>
          </thead>
          <tbody>
            {c.engines.map((e) => (
              <tr key={e.engine}>
                <td>{e.engine}</td>
                <td className="num">{formatCount(e.points)}</td>
                <td className="num">{formatCount(e.graded)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}
      {c.refusals.length > 0 ? (
        <details className="about">
          <summary>Why points are not scored ({formatCount(c.refusals.length)} reasons)</summary>
          <table className="readout">
            <thead>
              <tr>
                <th>Reason</th>
                <th>Setting</th>
                <th>Points</th>
              </tr>
            </thead>
            <tbody>
              {c.refusals.slice(0, 12).map((r) => (
                <tr key={`${r.code}|${r.subject}`}>
                  <td>{r.code}</td>
                  <td>{r.subject || '—'}</td>
                  <td className="num">{formatCount(r.points)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {c.refusals.length > 12 ? <p>The {formatCount(c.refusals.length - 12)} smaller reasons are in classes.json.</p> : null}
        </details>
      ) : null}
      {c.substitutions.length > 0 ? (
        <details className="about" open={c.kind === 'reconstructed'}>
          <summary>What differs from the run ({formatCount(c.substitutions.length)} named substitutions)</summary>
          <table className="readout">
            <thead>
              <tr>
                <th>Kind</th>
                <th>Subject</th>
                <th>Points</th>
                <th>Detail</th>
              </tr>
            </thead>
            <tbody>
              {c.substitutions.map((s) => (
                <tr key={`${s.kind}|${s.subject}|${s.detail}`}>
                  <td>{s.kind}</td>
                  <td>{s.subject}</td>
                  <td className="num">{formatCount(s.points)}</td>
                  <td style={{ whiteSpace: 'normal' }}>{s.detail || '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </details>
      ) : null}
      <details className="about">
        <summary>Where these numbers come from</summary>
        <p>{c.provenance.command}</p>
        <p>{`Data pulled ${c.provenance.pulled_at}${c.provenance.derived_at ? `, derived ${c.provenance.derived_at}` : ''}.`}</p>
        <div className="about-prov">
          {Object.entries(c.provenance.heads).map(([k, v]) => (
            <div className="kv" key={k}>
              <span>{k}</span>
              <span className="v">{String(v).length > 16 ? String(v).slice(0, 12) : String(v)}</span>
            </div>
          ))}
        </div>
      </details>
    </section>
  )
}

export function Classes({ doc, error }: { doc: ClassesDoc | null; error: string | null }) {
  return (
    <div className="classes">
      <h2 className="viewhead">Classes of points</h2>
      <p className="context">
        Each class is counted on its own: the regular InferenceX run, the SGLang points the final census scored, InferenceX points
        scored from a reconstructed recipe (kept apart, graded G4 at best), and Red Hat's configiq dataset scored by simulation
        (provisional). Counts are never added across classes.
      </p>
      {error ? (
        <div className="viewerror" role="alert">
          <h3>Could not load the classes.</h3>
          <pre>
            <code>{error}</code>
          </pre>
        </div>
      ) : doc == null ? (
        <div className="loading">Loading the classes…</div>
      ) : (
        <>
          <p className="stat-hint">
            Latest run{doc.snapshot_id ? ` ${doc.snapshot_id}` : ''}, built {doc.generated_at}.
          </p>
          {doc.classes.map((c) => (
            <ClassCard key={c.id} c={c} />
          ))}
        </>
      )}
    </div>
  )
}
