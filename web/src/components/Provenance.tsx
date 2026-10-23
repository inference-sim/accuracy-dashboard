/**
 * The "match" tooltip for a v2 point (#30, Discussion #28): is this comparison apples to apples?
 * Written for a reader of the results, not a BLIS developer, so it lists ONLY what differs between
 * the measured run and what BLIS simulated, in plain words:
 *
 *   - settings BLIS couldn't match exactly (approximated), with what each side used;
 *   - settings the run didn't record, which BLIS filled with its own default;
 *   - how far the run's vLLM build is from the release BLIS models.
 *
 * Everything that matched is summed up in one sentence. The full per-setting record stays in
 * summary.json (point.fidelity) for anyone who wants it. v1 points have no record and render
 * nothing.
 */
import { Term } from './Term'
import type { Fidelity, FidelityArg } from '../types'

/** Plain names for settings a reader may see here. Anything else falls back to its own name. */
const LABEL: Record<string, string> = {
  'attention_config.indexer_kv_dtype': 'Indexer cache format',
  'attention_config.indexer_sparse_logits': 'Sparse indexer',
  'attention_config.backend': 'Attention kernel',
  attention_backend: 'Attention kernel',
  'attention_config.use_prefill_query_quantization': 'Prefill query quantization',
  max_num_seqs: 'Max concurrent requests',
  max_num_batched_tokens: 'Max tokens per step',
  block_size: 'KV cache block size',
}

/** What BLIS used, for the placeholder values the record carries for an approximation. */
const BLIS_SIDE: Record<string, string> = {
  'catalog default': 'the model’s default',
  'v0.31.0 selection': 'the default for this GPU',
}

function label(arg: string): string {
  return LABEL[arg] ?? arg.split('.').slice(-1)[0]!.replace(/_/g, ' ')
}

/** vLLM's attention-backend enum names, as a reader would say them. An unknown name is shown as
 *  is (lowercased, underscores as spaces) rather than guessed at. */
const KERNEL: Record<string, string> = {
  FLASHINFER_MLA_SPARSE_DSV41: 'FlashInfer sparse MLA',
  FLASHMLA_MEGA_ATTN_DSV41: 'FlashMLA mega-attention',
  FLASHMLA_SPARSE_DSV41: 'FlashMLA sparse',
  FLASHINFER: 'FlashInfer',
  FLASH_ATTN: 'FlashAttention',
  TRITON_ATTN: 'Triton',
}

function value(v: unknown): string {
  if (v === true) return 'on'
  if (v === false) return 'off'
  if (v == null) return '—'
  const s = String(v)
  if (BLIS_SIDE[s]) return BLIS_SIDE[s]!
  if (KERNEL[s]) return KERNEL[s]!
  return /^[A-Z0-9_]{12,}$/.test(s) ? s.toLowerCase().replace(/_/g, ' ') : s
}

/** The settings BLIS estimated, side by side. A popover lives inside a <span> trigger, so this
 *  uses spans laid out as a table (CSS display: table), never a real <table> element. */
function DiffTable({ args }: { args: FidelityArg[] }) {
  return (
    <span className="prov-tbl" role="table" aria-label="settings BLIS estimated">
      <span className="prov-tr prov-th" role="row">
        <span role="columnheader">Setting</span>
        <span role="columnheader">This run</span>
        <span role="columnheader">BLIS</span>
      </span>
      {args.map((a) => (
        <span className="prov-tr" role="row" key={a.arg}>
          <span role="cell">{label(a.arg)}</span>
          <span role="cell" className="mono">{value(a.measured)}</span>
          <span role="cell">{value(a.blis)}</span>
        </span>
      ))}
    </span>
  )
}

export function ProvenanceBody({ fidelity: f, measuredDate }: { fidelity: Fidelity; measuredDate?: string }) {
  const approx = f.args.filter((a) => a.match === 'approximated')
  const defaults = f.args.filter((a) => a.match === 'blis_default')
  const issues = [...new Set(approx.map((a) => a.upstream).filter((u): u is string => !!u))]
  const dist = f.build.distance
  const exact = f.status !== 'approximate'
  return (
    <span className="prov-body">
      <span className="prov-h">
        {exact ? 'Exact match' : 'Estimated'}
        {measuredDate && <span className="prov-dim"> · measured {measuredDate}</span>}
      </span>
      <span className="prov-row">
        {exact
          ? 'BLIS simulated the exact settings this run used.'
          : 'BLIS simulated this run’s settings, except these, which it estimated:'}
      </span>
      {approx.length > 0 && <DiffTable args={approx} />}
      {issues.length > 0 && (
        <span className="prov-row prov-dim">
          BLIS can’t represent {approx.length === 1 ? 'this setting' : 'these settings'} yet ({issues.join(', ')}). Counted
          only in “all (including estimations)”.
        </span>
      )}
      {defaults.map((a) => (
        <span className="prov-row" key={a.arg}>
          <b>{label(a.arg)}</b>: not recorded by the run, so BLIS used its default ({value(a.blis)})
        </span>
      ))}
      {dist != null && dist !== 0 && (
        <span className="prov-row prov-dim">
          vLLM build: {Math.abs(dist).toLocaleString('en-US')} commits {dist > 0 ? 'newer' : 'older'} than{' '}
          {f.build.ref}, the release BLIS models.
        </span>
      )}
    </span>
  )
}

/** The ⓘ / ≈ trigger for a point's match details; nothing for a v1 point. */
export function ProvenanceTip({ fidelity, measuredDate }: { fidelity?: Fidelity; measuredDate?: string }) {
  if (!fidelity) return null
  const approx = fidelity.status === 'approximate'
  return (
    <Term
      content={<ProvenanceBody fidelity={fidelity} measuredDate={measuredDate} />}
      popClass="term-pop-wide"
      ariaLabel={approx ? 'estimated: what differs' : 'exact match'}
    >
      <span className={`prov-mark${approx ? ' approx' : ''}`} aria-hidden="true">
        {approx ? '≈' : '✓'}
      </span>
    </Term>
  )
}
