/**
 * Client-side aggregation (RFC §4.4 point 1, B3). The precomputed node `metrics` in
 * summary.json are valid only for the unfiltered, on-target tree. The moment a filter (vLLM
 * version, hardware, multi-node, tier) hides some points, every parent aggregate and shape
 * error above them would be stale. So we recompute aggregates from the VISIBLE leaf points —
 * never trusting a stored parent number under a filter.
 *
 * The MAPE/shape arithmetic replicated here is identical to the orchestrator's
 * (orchestrator/build_summary.py) and to cmd/metricscore's simulatedErrors: the documented
 * definition of the numbers. Shape re-anchors both sides at the sweep's lowest surviving
 * concurrency and excludes the anchor; every level averages |individual point errors|, never
 * child-node means.
 */
import type { Metric, MetricBlock, MetricBlockPair, Summary, TierKey } from './types'

/** A leaf point flattened out of the tree with its full ancestry, for filtering + regrouping. */
export interface FlatPoint {
  model: string
  modelVllm: string | null
  modelOnTarget: boolean | null
  workloadLabel: string
  isl: number | null
  osl: number | null
  gpu: string
  precision: string | null
  framework: string
  engineVersion: string | null
  onTargetVersion: boolean | null
  isMultinode: boolean
  topoLabel: string
  parallelism: Record<string, number>
  serving: string | null
  specMethod: string | null
  concurrency: number
  tier: TierKey
  measTtftMs: number | null
  measTpotMs: number | null
  predTtftMs: number | null
  predTpotMs: number | null
  errTtft: number | null
  errTpot: number | null
  shapeTtft: number | null
  shapeTpot: number | null
  shapeReason: string | null
  /** Stable identity across snapshots for row-select + same-points work. */
  sweepKey: string
}

/** Flatten the whole matrix into leaf points carrying their ancestry. */
export function flattenPoints(summary: Summary): FlatPoint[] {
  const out: FlatPoint[] = []
  for (const m of summary.matrix) {
    for (const w of m.rows) {
      for (const g of w.rows) {
        for (const t of g.rows) {
          for (const p of t.rows) {
            out.push({
              model: m.model,
              modelVllm: m.vllm_version,
              modelOnTarget: m.on_target_version,
              workloadLabel: w.label,
              isl: w.isl,
              osl: w.osl,
              gpu: g.label,
              precision: g.precision,
              framework: t.framework,
              engineVersion: t.engine_version,
              onTargetVersion: t.on_target_version,
              isMultinode: t.is_multinode,
              topoLabel: t.label,
              parallelism: t.parallelism,
              serving: t.serving,
              specMethod: t.spec_method,
              concurrency: p.concurrency,
              tier: p.tier,
              measTtftMs: p.measured?.ttft_ms ?? null,
              measTpotMs: p.measured?.tpot_ms ?? null,
              predTtftMs: p.predicted?.ttft_ms ?? null,
              predTpotMs: p.predicted?.tpot_ms ?? null,
              errTtft: p.error_pct?.ttft ?? null,
              errTpot: p.error_pct?.tpot ?? null,
              shapeTtft: p.shape?.ttft ?? null,
              shapeTpot: p.shape?.tpot ?? null,
              shapeReason: p.shape_reason ?? null,
              sweepKey: `${m.model}|${w.label}|${g.label}|${t.label}`,
            })
          }
        }
      }
    }
  }
  return out
}

function meanAbs(values: (number | null)[]): { mean: number | null; n: number } {
  let acc = 0
  let n = 0
  for (const v of values) {
    if (v != null && Number.isFinite(v)) {
      acc += Math.abs(v)
      n++
    }
  }
  return n > 0 ? { mean: acc / n, n } : { mean: null, n: 0 }
}

/** A metricBlock recomputed from a flat list of points, for one tier. */
export function aggregate(points: FlatPoint[], tier: TierKey): MetricBlock {
  const scoped = tier === 'measured_or_resolved' ? points.filter((p) => p.tier === 'measured_or_resolved') : points
  const mapeTtft = meanAbs(scoped.map((p) => p.errTtft))
  const mapeTpot = meanAbs(scoped.map((p) => p.errTpot))
  const shapeTtft = meanAbs(scoped.map((p) => p.shapeTtft))
  const shapeTpot = meanAbs(scoped.map((p) => p.shapeTpot))
  return {
    mape: { ttft: mapeTtft.mean, tpot: mapeTpot.mean, n: Math.max(mapeTtft.n, mapeTpot.n) },
    shape: { ttft: shapeTtft.mean, tpot: shapeTpot.mean, n: Math.max(shapeTtft.n, shapeTpot.n) },
  }
}

export function aggregatePair(points: FlatPoint[]): MetricBlockPair {
  return { measured_or_resolved: aggregate(points, 'measured_or_resolved'), all: aggregate(points, 'all') }
}

export const METRICS: Metric[] = ['ttft', 'tpot']
