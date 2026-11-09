/**
 * TypeScript mirror of schemas/summary.v1.json, summary.v2.json and summary.v3.json (RFC §4.4).
 * Hand-maintained alongside the local schemas: a format break is caught in CI by
 * validate_summary.py / validate_summary_v2.py, and `schema_version` gates the loader here
 * (load.ts) before the site renders anything. Everything v2 and v3 add is optional, so v1 data
 * types and renders exactly as before.
 */

export type Metric = 'ttft' | 'tpot'
export type TierKey = 'measured_or_resolved' | 'all'

/** The text a figure over fewer than min_points points is published and shown as (COV-11). */
export const TOO_FEW = 'too few points'
export type TooFew = typeof TOO_FEW

export interface MapeShape {
  /** v3: 'too few points' where the points holding the value are fewer than min_points. */
  ttft: number | null | TooFew
  tpot: number | null | TooFew
  n: number
}

export interface MetricBlock {
  mape: MapeShape
  shape: MapeShape
  noise_floor_pct?: number | null
}

export interface MetricBlockPair {
  measured_or_resolved: MetricBlock
  all: MetricBlock
}

export interface CoverageCount {
  scored: number
  total: number
}

/** One classified vLLM setting in a v2 fidelity record (schemas/fidelity.v2.json). */
export interface FidelityArg {
  arg: string
  measured: string | number | boolean | null
  /** blis_default appears in v2 records only. */
  source?: 'launch_config' | 'args' | 'resolved_config' | 'engine_line' | 'api_row' | 'blis_default'
  blis: string | number | boolean | null
  blis_field?: string
  match: 'exact' | 'mapped' | 'inert' | 'blis_default' | 'approximated' | 'differs' | 'absent_in_blis' | 'unreadable' | 'conflict'
  rule?: string
  note?: string
  occurrences?: number
  values?: unknown[]
}

export interface FidelityResolved {
  quantity: string
  measured: number | string | null
  blis: number | string | null
  match: 'exact' | 'differs' | 'unreadable' | 'conflict' | 'incomparable'
  occurrences?: number
  delta?: number | string | null
  ratio?: string | null
  reason?: string
}

/** A closeness grade (design §11.3): G1 to G4 are graded, G5 is not scored. */
export type Grade = 'G1' | 'G2' | 'G3' | 'G4' | 'G5'
export type GradedGrade = Exclude<Grade, 'G5'>

/** v3: one condition that holds a point below G1, named on the point. */
export interface Substitution {
  kind: string
  subject: string
  detail: string
}

/** What a point's run did versus what BLIS was given (v2, Discussion #28), and on v3 its grade. */
export interface Fidelity {
  /** v2 only. */
  status?: 'exact' | 'approximate' | 'not_scored'
  reasons?: string[]
  /** v3 only: the point's grade, every substitution, and the engine release the run measured
   *  (null for a nightly or custom build). */
  grade?: GradedGrade
  substitutions?: Substitution[]
  run_release?: string | null
  build: {
    image: string
    commit: string | null
    source: string | null
    ref: string
    distance: number | null
    /** exact: the build BLIS models. Older v2 records have no match and read as exact. */
    match?: 'exact' | 'estimated'
    why?: 'custom_build' | 'outside_distance' | 'commit_unresolvable' | 'commit_conflict'
  }
  args: FidelityArg[]
  resolved: FidelityResolved[]
  replay?: {
    client: string
    client_version: string
    scenario: string
    replayed_as?: string
    concurrency: number
    duration_s?: number
    corpus: string
    corpus_sha256: string
    seed: number
    trajectory_start?: { min_ratio?: number; max_ratio?: number }
  }
  /** Single-turn: how the client's requests were replayed, and each difference from the run's
   *  client (COV-12). A point naming a difference is approximate. */
  requests?: {
    client: string
    start: 'cold' | 'primed'
    copies: number
    count: number
    differences: { kind: 'client_difference'; subject: 'send_gap' | 'sent_prompt_lengths'; detail: string }[]
  }
  blis_kernel_provenance?: unknown
}

/** v2: a point's identity; point_id is the sha256 of its canonical JSON. A unit identity in
 *  snapshots from this release on, the eight-field legacy identity in those published before
 *  (published snapshots never change, COV-8). */
export type PointIdentity = UnitIdentity | LegacyPointIdentity

/** The ledger unit identity (design §10.2): point_id is the ledger's unit_id. */
export interface UnitIdentity {
  source: 'inferencex'
  model: string
  hardware: string
  precision: string
  framework: string
  benchmark_type: string
  configuration_hash: string
  recipe_fingerprint: string | null
  conc: number
  measured_date: string
  benchmark_run: number | null
}

/** The identity of a point in a snapshot published before point ids were unit ids. */
export interface LegacyPointIdentity {
  model: string
  hardware: string
  precision: string
  framework: string
  benchmark_type: string
  recipe: string
  conc: number
  measured_date: string
}

export interface PointNode {
  level: 'point'
  concurrency: number
  tier: TierKey
  measured?: { ttft_ms: number | null; tpot_ms: number | null }
  predicted?: { ttft_ms: number | null; tpot_ms: number | null }
  error_pct?: { ttft: number | null; tpot: number | null }
  shape?: { ttft: number | null; tpot: number | null } | null
  shape_reason?: string | null
  /** v2 only: the point's identity hash, its measurement date and its fidelity record. */
  point_id?: string
  /** v2: the point's identity in InferenceX's own terms (point_id is the sha256 of it), so
   *  summary.json inverts losslessly back to a contract for IX-only merges. */
  identity?: PointIdentity
  measured_date?: string
  /** v2: the measured curve the point's trend is computed in; repeats at one concurrency are
   *  separate sweeps of the same deployment. */
  sweep_id?: string
  /** v2: InferenceX ran this measurement more than once with identical BLIS inputs; `measured`
   *  is the runs' mean and each run is listed here. */
  repeats?: { point_id: string; identity: PointIdentity; measured: { ttft_ms: number | null; tpot_ms: number | null } }[]
  fidelity?: Fidelity
}

export interface TopologyNode {
  level: 'topology'
  framework: string
  engine_version: string | null
  precision: string | null
  is_multinode: boolean
  parallelism: Record<string, number>
  serving: string | null
  spec_method: string | null
  label: string
  coverage: CoverageCount
  metrics: MetricBlockPair
  rows: PointNode[]
}

export interface GpuNode {
  level: 'gpu'
  label: string
  precision: string | null
  coverage: CoverageCount
  metrics: MetricBlockPair
  rows: TopologyNode[]
}

export interface WorkloadNode {
  level: 'workload'
  label: string
  isl: number | null
  osl: number | null
  coverage: CoverageCount
  metrics: MetricBlockPair
  rows: GpuNode[]
}

export interface ModelNode {
  level: 'model'
  model: string
  display_name?: string
  source?: string
  vllm_version: string | null
  coverage: CoverageCount
  metrics: MetricBlockPair
  rows: WorkloadNode[]
}

export interface Provenance {
  blis: {
    release: string
    commit_sha: string
    catalog: string
    registry: string
    extractor_version: string
  }
  ground_truth: {
    source: string
    source_url?: string
    release_tag: string
    measurement_date_through?: string | null
    measurement_sha256: string
  }
  evaluator_commit: string
  scorer: string
  /** v3 only: the engine release the scoring simulator runs (stack.json). */
  engine?: { kind: string; version: string }
  /** v2 and v3: which ingest produced the snapshot ('api'); absent on v1 (the db-dump pipeline). */
  ingest?: 'api'
  vllm_ref?: string
  vllm_max_distance?: number
  /** v2 only. */
  policy_sha256?: string
  /** v3 only: the sha256 of the engine's fields.json the scorer read. */
  fields_sha256?: string
  pulled_at?: string
  /** v2 only. */
  corpus?: { dataset: string; revision: string; sha256: string } | null
  /** v3 only: each AgentX corpus by alias, pinned by its catalog replay workload. */
  corpora?: { alias: string; workload: string; dataset: string; revision: string; sha256: string }[]
}

export interface Coverage {
  /** v1 and v2: the matrix's points. */
  scored?: number
  not_scored: number
  multinode_hidden?: number
  failed: number
  /** v2: InferenceX runs folded into another point as a repeat of it. */
  repeat_runs_folded?: number
  measured_excluded?: number
  not_scored_reasons?: Record<string, number>
  /** v3 (COV-7): every anchor unit, those graded G1 to G4, and the split by engine, engine
   *  release, chip and grade, with the records the ledger left out. */
  points?: number
  graded?: number
  share_graded?: number | null
  left_out_records?: number
  by_grade?: Record<Grade, number>
}

/** v2 and v3: a point InferenceX measured that this run didn't score. Never rendered. */
export interface NotScoredPoint {
  point_id: string
  measured_date: string
  model: string
  hardware: string
  /** v2 */
  reasons?: string[]
  /** v3 */
  g5_reason?: { code: string; subject?: string }
  [k: string]: unknown
}

/** v3: one published figure and the number of points it covers (COV-11). */
export interface Figure {
  mape: number | TooFew
  n: number
}

/** v3: the headline over every graded point, and each grade's share and accuracy. */
export interface HeadlineBlock {
  points: number
  graded: number
  not_scored: number
  headline: { ttft: Figure; tpot: Figure }
  grades: Record<GradedGrade, { points: number; share: number | TooFew; ttft: Figure; tpot: Figure }>
}

export interface Summary {
  schema_version: 1 | 2 | 3
  snapshot_id: string
  generated_at: string
  provenance: Provenance
  coverage: Coverage
  known_artefacts?: string[]
  metrics: Metric[]
  metricscore_comparison?: unknown
  totals: MetricBlockPair
  matrix: ModelNode[]
  scope: {
    multinode?: string
    measured_exclusions?: string[]
    vllm_version_filter?: string
  }
  /** v2 and v3. */
  not_scored?: NotScoredPoint[]
  /** v3 only. */
  min_points?: number
  headline?: HeadlineBlock
  backlog?: { top: { reason: string; points: number }[] }
  failed?: { point_id: string; faults: string[]; [k: string]: unknown }[]
}

/** Whether a point is below the strict tier: on v3 any grade but G1, on v2 an approximate
 *  status. A v1 point has no record and is never "estimated". */
export function isEstimated(f: Fidelity | undefined): boolean {
  if (!f) return false
  return f.grade ? f.grade !== 'G1' : f.status === 'approximate'
}

/** Any non-leaf node in the drill-down tree carries metrics + coverage + child rows. */
export type TreeNode = ModelNode | WorkloadNode | GpuNode | TopologyNode
