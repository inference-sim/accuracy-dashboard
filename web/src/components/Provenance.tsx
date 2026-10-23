/**
 * The "match" tooltip for a v2 point (#30, Discussion #28): is this comparison apples to apples?
 * Written for a reader of the results, not a BLIS developer, so it lists ONLY what differs between
 * the measured run and what BLIS simulated, in plain words:
 *
 *   - settings BLIS couldn't match exactly (approximated), with what each side used;
 *   - the run's vLLM build, when it isn't the one BLIS models.
 *
 * A setting the run didn't pass isn't listed: vLLM then ran its own default, and BLIS uses the
 * same default (vLLM v0.31.0's rule for the part), so both sides ran the same value.
 *
 * How far the run's vLLM build is from the release BLIS models is also on the point's vLLM
 * version (VersionTip).
 *
 * Everything that matched is summed up in one sentence. The full per-setting record stays in
 * summary.json (point.fidelity) for anyone who wants it. v1 points have no record and render
 * nothing.
 */
import { Term } from './Term'
import { formatVersion } from '../format'
import type { Fidelity, FidelityArg } from '../types'

/** Plain names for settings a reader may see here. Anything else falls back to its own name. */
const LABEL: Record<string, string> = {
  quantization: 'Weight format',
  'attention_config.indexer_kv_dtype': 'Indexer cache format',
  'attention_config.indexer_sparse_logits': 'Sparse indexer',
  'attention_config.backend': 'Attention kernel',
  attention_backend: 'Attention kernel',
  'attention_config.use_prefill_query_quantization': 'Prefill query quantization',
  max_num_seqs: 'Max concurrent requests',
  max_num_batched_tokens: 'Max tokens per step',
  block_size: 'KV cache block size',
}


function label(arg: string): string {
  return LABEL[arg] ?? arg.split('.').slice(-1)[0]!.replace(/_/g, ' ')
}

/** vLLM enum names (attention backends, packed KV-cache records) as a reader would say them. An
 *  unknown name is shown as is (lowercased, underscores as spaces) rather than guessed at. */
const KERNEL: Record<string, string> = {
  // Weight formats as vLLM names them, said plainly (quantization).
  modelopt_fp4: 'nvfp4',
  modelopt_mixed: 'nvfp4 + mxfp8 (mixed)',
  gpt_oss_mxfp4: 'mxfp4 (gpt-oss MoE kernels)',
  nvfp4_ds_mla: 'default kernel, NVFP4 packed KV cache',
  fp8_ds_mla: 'default kernel, FP8 packed KV cache',
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
  if (KERNEL[s]) return KERNEL[s]!
  return /^[A-Z0-9_]{12,}$/.test(s) ? s.toLowerCase().replace(/_/g, ' ') : s
}

/** The settings BLIS estimated, side by side. A popover lives inside a <span> trigger, so this
 *  uses spans laid out as a table (CSS display: table), never a real <table> element. */
function DiffTable({ args, build }: { args: FidelityArg[]; build: { run: string; ref: string } | null }) {
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
      {build && (
        <span className="prov-tr" role="row">
          <span role="cell">vLLM build</span>
          <span role="cell">{build.run}</span>
          <span role="cell">{build.ref}</span>
        </span>
      )}
    </span>
  )
}

/** Why a run's build isn't the one BLIS models, in plain words. */
function buildDiff(b: Fidelity['build']): string | null {
  if (b.match !== 'estimated') return null
  switch (b.why) {
    case 'outside_distance':
      return `${Math.abs(b.distance ?? 0).toLocaleString('en-US')} commits ${(b.distance ?? 0) > 0 ? 'newer' : 'older'} than ${b.ref}`
    case 'custom_build':
      return 'a custom build'
    default:
      return 'a build that can’t be traced to a vLLM commit'
  }
}

export function ProvenanceBody({ fidelity: f }: { fidelity: Fidelity }) {
  const approx = f.args.filter((a) => a.match === 'approximated')
  const build = buildDiff(f.build)
  const exact = f.status !== 'approximate'
  return (
    <span className="prov-body">
      <span className="prov-h">{exact ? 'Exact match' : 'Estimated'}</span>
      <span className="prov-row">
        {exact
          ? 'BLIS simulated the exact settings this run used.'
          : approx.length > 0
            ? 'BLIS simulated this run’s settings, except these, which it estimated:'
            : 'BLIS simulated the exact settings this run used, but not its vLLM build:'}
      </span>
      {(approx.length > 0 || build) && <DiffTable args={approx} build={build ? { run: build, ref: f.build.ref } : null} />}
    </span>
  )
}

/** The ⓘ / ≈ trigger for a point's match details; nothing for a v1 point. */
export function ProvenanceTip({ fidelity }: { fidelity?: Fidelity }) {
  if (!fidelity) return null
  const approx = fidelity.status === 'approximate'
  return (
    <Term
      content={<ProvenanceBody fidelity={fidelity} />}
      popClass="term-pop-wide"
      ariaLabel={approx ? 'estimated: what differs' : 'exact match'}
    >
      <span className={`prov-mark${approx ? ' approx' : ''}`} aria-hidden="true">
        {approx ? '≈' : '✓'}
      </span>
    </Term>
  )
}

/** A point's vLLM version. On a v2 point, hovering it says how far the run's build is from the
 *  release BLIS models; a v1 point (no build record) shows the plain version. */
export function VersionTip({ version, fidelity }: { version: string; fidelity?: Fidelity }) {
  const badge = <span className="ver neutral">{formatVersion(version)}</span>
  if (!fidelity || (fidelity.build.distance == null && fidelity.build.match !== 'estimated')) return badge
  return (
    <Term content={<VersionBody build={fidelity.build} />} ariaLabel="vLLM build">
      {badge}
    </Term>
  )
}

export function VersionBody({ build: b }: { build: Fidelity['build'] }) {
  const d = b.distance ?? 0
  return (
    <span className="prov-body">
      <span className="prov-row">
        {b.distance == null
          ? `This run’s vLLM build is ${buildDiff(b) ?? 'not traced to a vLLM commit'}; BLIS models ${b.ref}.`
          : d === 0
          ? `This run’s vLLM build is ${b.ref}, the release BLIS models.`
          : `This run’s vLLM build is ${Math.abs(d).toLocaleString('en-US')} commits ${d > 0 ? 'newer' : 'older'} than ${b.ref}, the release BLIS models.`}
      </span>
    </span>
  )
}
