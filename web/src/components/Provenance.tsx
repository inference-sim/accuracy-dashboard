/**
 * The provenance tooltip for a v2 point (#30, Discussion #28): what the measured run did versus
 * what BLIS was given. Built on the accessible <Term> popover, so it opens on hover and keyboard
 * focus and closes on Esc / blur.
 *
 * It shows, from the point's fidelity record:
 *   - the vLLM build commit and its distance from VLLM_REF;
 *   - each setting BLIS was given, with where it came from (launch config / args / the engine's
 *     resolved config / an engine log line / BLIS's own default);
 *   - mapped settings with the BLIS field they went to (moe_backend → engine.moe_backend);
 *   - approximated settings (a quantized format BLIS can't state) with their note and issue;
 *   - inert ones (recorded only, e.g. the router);
 *   - the BLIS defaults used, with the resolver rule;
 *   - the engine-outcome comparison (vLLM's KV pool vs BLIS's).
 *
 * v1 points have no fidelity record, and this renders nothing for them.
 */
import { Term } from './Term'
import type { Fidelity, FidelityArg } from '../types'

const SOURCE: Record<string, string> = {
  launch_config: 'launch config',
  args: 'server args',
  resolved_config: 'engine config',
  engine_line: 'engine log',
  api_row: 'InferenceX row',
  blis_default: 'BLIS default',
}

/** The settings worth listing: everything BLIS was given, plus the approximated and inert ones
 *  the record names. Fields printed at vLLM's own default and dropped are not in the record. */
function given(args: FidelityArg[]): FidelityArg[] {
  return args.filter((a) => a.match === 'exact' || a.match === 'mapped')
}

function show(v: unknown): string {
  if (v == null) return '—'
  if (typeof v === 'string') return v.length > 40 ? `${v.slice(0, 37)}…` : v
  return String(v)
}

function shortSha(s: string | null): string {
  return s ? s.slice(0, 10) : '—'
}

export function ProvenanceBody({ fidelity: f, measuredDate }: { fidelity: Fidelity; measuredDate?: string }) {
  const settings = given(f.args)
  const mapped = f.args.filter((a) => a.match === 'mapped' && a.blis_field)
  const approx = f.args.filter((a) => a.match === 'approximated')
  const inert = f.args.filter((a) => a.match === 'inert' && a.measured != null)
  const defaults = f.args.filter((a) => a.match === 'blis_default')
  const dist = f.build.distance
  return (
    <span className="prov-body">
      <span className="prov-h">
        {f.status === 'approximate' ? 'Approximate match' : 'Exact match'}
        {measuredDate && <span className="prov-dim"> · measured {measuredDate}</span>}
      </span>
      <span className="prov-row">
        <b>vLLM build</b> <span className="mono">{shortSha(f.build.commit)}</span>
        {dist != null && (
          <>
            {' '}· {dist === 0 ? 'at' : `${Math.abs(dist).toLocaleString('en-US')} commits ${dist > 0 ? 'after' : 'before'}`}{' '}
            <span className="mono">{f.build.ref}</span>
          </>
        )}
        {f.build.source && <span className="prov-dim"> (commit from {f.build.source.replace(/_/g, ' ')})</span>}
      </span>
      {approx.length > 0 && (
        <span className="prov-sec">
          <b>Approximated</b>
          {approx.map((a) => (
            <span className="prov-row" key={a.arg}>
              <span className="mono">{a.arg}</span> {show(a.measured)} → BLIS {show(a.blis)}
              {a.note && <span className="prov-dim"> — {a.note}</span>}
              {a.upstream && <span className="prov-dim"> ({a.upstream})</span>}
            </span>
          ))}
        </span>
      )}
      {defaults.length > 0 && (
        <span className="prov-sec">
          <b>BLIS defaults</b> (not recorded by the run)
          {defaults.map((a) => (
            <span className="prov-row" key={a.arg}>
              <span className="mono">{a.arg}</span> = {show(a.blis)}
              {a.rule && <span className="prov-dim"> — {a.rule}</span>}
            </span>
          ))}
        </span>
      )}
      {mapped.length > 0 && (
        <span className="prov-sec">
          <b>Mapped</b>
          {mapped.map((a) => (
            <span className="prov-row" key={a.arg}>
              <span className="mono">{a.arg}</span> → <span className="mono">{a.blis_field}</span>
            </span>
          ))}
        </span>
      )}
      <span className="prov-sec">
        <b>Settings given to BLIS</b> ({settings.length}, each as the run recorded it)
        {/* grouped by where the value came from, so the list stays short */}
        {Object.entries(
          settings.reduce<Record<string, FidelityArg[]>>((acc, a) => {
            const k = SOURCE[a.source ?? ''] ?? a.source ?? 'run'
            ;(acc[k] ??= []).push(a)
            return acc
          }, {}),
        ).map(([src, as]) => (
          <span className="prov-row" key={src}>
            <span className="prov-dim">from {src}: </span>
            {as.map((a, i) => (
              <span key={a.arg}>
                {i > 0 && ', '}
                <span className="mono">{a.arg.split('.').slice(-1)[0]}</span> {show(a.blis)}
              </span>
            ))}
          </span>
        ))}
      </span>
      {inert.length > 0 && (
        <span className="prov-sec">
          <b>Recorded, no effect on timing</b>
          <span className="prov-row prov-dim">
            {inert.map((a) => `${a.arg.split('.').slice(-1)[0]} ${show(a.measured)}`).join(' · ')}
          </span>
        </span>
      )}
      {f.resolved.length > 0 && (
        <span className="prov-sec">
          <b>Engine outcome</b>
          {f.resolved.map((r) => (
            <span className="prov-row" key={r.quantity}>
              <span className="mono">{r.quantity.replace(/_/g, ' ')}</span>: vLLM {show(r.measured)}, BLIS {show(r.blis)}
              {r.ratio && <span className="prov-dim"> (×{r.ratio})</span>}
            </span>
          ))}
        </span>
      )}
    </span>
  )
}

/** The ⓘ trigger for a point's provenance; nothing for a v1 point. */
export function ProvenanceTip({ fidelity, measuredDate }: { fidelity?: Fidelity; measuredDate?: string }) {
  if (!fidelity) return null
  return (
    <Term content={<ProvenanceBody fidelity={fidelity} measuredDate={measuredDate} />} popClass="term-pop-wide"
      ariaLabel="provenance: what the run did versus what BLIS was given">
      <span className={`prov-mark${fidelity.status === 'approximate' ? ' approx' : ''}`} aria-hidden="true">
        {fidelity.status === 'approximate' ? '≈' : 'ⓘ'}
      </span>
    </Term>
  )
}
