/**
 * TypeScript mirror of schemas/summary.v1.json (RFC §4.4). Hand-maintained alongside the
 * local schema: a format break is caught in CI by validate_summary.py against that schema,
 * and `schema_version` gates the loader here (load.ts) before the site renders anything.
 */

export type Metric = 'ttft' | 'tpot'
export type TierKey = 'measured_or_resolved' | 'all'

export interface MapeShape {
  ttft: number | null
  tpot: number | null
  n: number
}

export interface SamePointsDelta {
  tpot_mape: number | null
  ttft_mape: number | null
  n_intersect: number
}

export interface MetricBlock {
  mape: MapeShape
  shape: MapeShape
  noise_floor_pct?: number | null
  same_points_delta?: SamePointsDelta | null
}

export interface MetricBlockPair {
  measured_or_resolved: MetricBlock
  all: MetricBlock
}

export interface CoverageCount {
  scored: number
  total: number
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
}

export interface TopologyNode {
  level: 'topology'
  framework: string
  engine_version: string | null
  on_target_version: boolean | null
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
  on_target_version: boolean | null
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
}

export interface Coverage {
  scored: number
  not_scored: number
  multinode_hidden: number
  failed: number
  measured_excluded?: number
  not_scored_reasons: Record<string, number>
}

export interface Summary {
  schema_version: 1
  snapshot_id: string
  generated_at: string
  previous_snapshot_id: string | null
  provenance: Provenance
  coverage: Coverage
  known_artefacts?: string[]
  target_vllm: string
  metrics: Metric[]
  metricscore_comparison?: unknown
  totals: MetricBlockPair
  matrix: ModelNode[]
  scope: {
    multinode?: string
    measured_exclusions?: string[]
    vllm_version_filter: 'on-target'
  }
}

/** Any non-leaf node in the drill-down tree carries metrics + coverage + child rows. */
export type TreeNode = ModelNode | WorkloadNode | GpuNode | TopologyNode
