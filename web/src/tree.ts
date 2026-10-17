/**
 * Re-group filtered flat points into the summary drill-down tree
 * (model → workload → GPU → topology), each node's metrics recomputed from its own visible
 * points (RFC §4.4). This runs AFTER the filters, so a hidden point never contributes to a
 * parent aggregate — the "filters never show stale numbers" guarantee (B3).
 */
import { aggregatePair, type FlatPoint } from './aggregate'
import type { MetricBlockPair } from './types'

export interface RenderRow {
  level: 'model' | 'workload' | 'gpu' | 'topology'
  /** display label for the first column */
  label: string
  /** facet suffix shown in muted mono after the label */
  facet: string
  /** the metrics recomputed from this node's visible points */
  metrics: MetricBlockPair
  /** the distinct vLLM versions among this row's visible points. The badge shows the single
   *  version when there's exactly one; when a row pools several (model/workload/GPU rows almost
   *  always do), it shows "N versions" rather than an arbitrary pick (never claims one version
   *  for data that spans many). */
  versions: string[]
  /** count of visible points under this node */
  pointCount: number
  /** depth 0..3 → r0..r3 */
  depth: number
  /** stable id for expand/collapse + deep-link */
  id: string
  /** for topology rows, the sweepKey identifying its points table */
  sweepKey?: string
}

function group<T>(items: T[], keyfn: (t: T) => string): Map<string, T[]> {
  const m = new Map<string, T[]>()
  for (const it of items) {
    const k = keyfn(it)
    const arr = m.get(k)
    if (arr) arr.push(it)
    else m.set(k, [it])
  }
  return m
}

/** The distinct, sorted vLLM versions among a set of points — the honest version facet for a row. */
function distinctVersions(pts: FlatPoint[]): string[] {
  return [...new Set(pts.map((p) => p.engineVersion).filter((v): v is string => !!v))].sort()
}

/** Build the ordered, flattened render rows honoring which node ids are expanded. */
export function buildRows(points: FlatPoint[], expanded: Set<string>): RenderRow[] {
  const rows: RenderRow[] = []
  const byModel = group(points, (p) => p.model)
  for (const [model, mpts] of [...byModel.entries()].sort((a, b) => a[0].localeCompare(b[0]))) {
    const nWl = new Set(mpts.map((p) => p.workloadLabel)).size
    const nGpu = new Set(mpts.map((p) => p.gpu)).size
    const nTopo = new Set(mpts.map((p) => p.sweepKey)).size
    const modelId = `m:${model}`
    rows.push({
      level: 'model', label: model,
      facet: `${nGpu} gpu · ${nWl} wl · ${nTopo} topo`,
      metrics: aggregatePair(mpts), versions: distinctVersions(mpts),
      pointCount: mpts.length, depth: 0, id: modelId,
    })
    if (!expanded.has(modelId)) continue

    const byWl = group(mpts, (p) => p.workloadLabel)
    for (const [wl, wpts] of [...byWl.entries()].sort((a, b) => a[0].localeCompare(b[0]))) {
      const w0 = wpts[0]!
      const wlId = `${modelId}|w:${wl}`
      rows.push({
        level: 'workload', label: shortWorkload(wl),
        facet: w0.isl != null && w0.osl != null ? `isl ${w0.isl} · osl ${w0.osl}` : wl,
        metrics: aggregatePair(wpts), versions: distinctVersions(wpts),
        pointCount: wpts.length, depth: 1, id: wlId,
      })
      if (!expanded.has(wlId)) continue

      const byGpu = group(wpts, (p) => p.gpu)
      for (const [gpu, gpts] of [...byGpu.entries()].sort((a, b) => a[0].localeCompare(b[0]))) {
        const g0 = gpts[0]!
        const gpuId = `${wlId}|g:${gpu}`
        rows.push({
          level: 'gpu', label: gpu,
          facet: g0.precision ? g0.precision : '',
          metrics: aggregatePair(gpts), versions: distinctVersions(gpts),
          pointCount: gpts.length, depth: 2, id: gpuId,
        })
        if (!expanded.has(gpuId)) continue

        const byTopo = group(gpts, (p) => p.topoLabel)
        for (const [topo, tpts] of [...byTopo.entries()].sort((a, b) => a[0].localeCompare(b[0]))) {
          const t0 = tpts[0]!
          const topoId = `${gpuId}|t:${topo}`
          const facetBits = [t0.framework, t0.serving, t0.isMultinode ? 'multi-node' : 'single-node']
            .filter(Boolean)
            .join(' · ')
          rows.push({
            level: 'topology', label: topo,
            facet: facetBits,
            metrics: aggregatePair(tpts), versions: distinctVersions(tpts),
            pointCount: tpts.length, depth: 3, id: topoId,
            sweepKey: t0.sweepKey,
          })
        }
      }
    }
  }
  return rows
}

/** "1024:1024" → "1k / 1k" where round; else the raw label. */
export function shortWorkload(label: string): string {
  const parts = label.split(':')
  if (parts.length !== 2) return label
  const nice = (s: string): string => {
    const n = Number(s)
    if (!Number.isFinite(n)) return s
    return n % 1024 === 0 ? `${n / 1024}k` : n % 1000 === 0 ? `${n / 1000}k` : String(n)
  }
  return `${nice(parts[0]!)} / ${nice(parts[1]!)}`
}
