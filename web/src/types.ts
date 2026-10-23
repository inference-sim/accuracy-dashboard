/**
 * TypeScript mirror of schemas/summary.v1.json and schemas/summary.v2.json (RFC §4.4, #30).
 * Hand-maintained alongside the local schemas: a format break is caught in CI by
 * validate_summary.py / validate_summary_v2.py, and `schema_version` gates the loader here
 * (load.ts) before the site renders anything. Everything v2 adds is optional, so v1 data
 * types and renders exactly as before.
 */

export type Metric = 'ttft' | 'tpot'
export type TierKey = 'measured_or_resolved' | 'all'

export interface MapeShape {
  ttft: number | null
  tpot: number | null
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

/** One classified vLLM setting in a v2 fidelity record (orchestrator/ingest/fidelity.schema.json). */
export interface FidelityArg {
  arg: string
  measured: string | number | boolean | null
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

/** What a point's run did versus what BLIS was given (v2, Discussion #28). */
export interface Fidelity {
  status: 'exact' | 'approximate' | 'not_scored'
  reasons?: string[]
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
  blis_kernel_provenance?: unknown
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
  measured_date?: string
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
  scorer: 'signedprobe'
  /** v2 only: which ingest produced the snapshot ('api'); absent on v1 (the db-dump pipeline). */
  ingest?: 'api'
  vllm_ref?: string
  vllm_max_distance?: number
  policy_sha256?: string
  pulled_at?: string
  corpus?: { dataset: string; revision: string; sha256: string } | null
}

export interface Coverage {
  scored: number
  not_scored: number
  multinode_hidden: number
  failed: number
  measured_excluded?: number
  not_scored_reasons: Record<string, number>
}

/** v2 only: a point InferenceX measured that this run didn't score. Never rendered. */
export interface NotScoredPoint {
  point_id: string
  measured_date: string
  model: string
  hardware: string
  reasons: string[]
  [k: string]: unknown
}

export interface Summary {
  schema_version: 1 | 2
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
  /** v2 only. */
  not_scored?: NotScoredPoint[]
}

/** Any non-leaf node in the drill-down tree carries metrics + coverage + child rows. */
export type TreeNode = ModelNode | WorkloadNode | GpuNode | TopologyNode
