/**
 * Slicing (design COV-13): the scored points cut by any attribute they record, each slice with its
 * point count, role-key count, coverage and accuracy. A slice over fewer than the minimum role
 * keys shows no accuracy, only the count in its place; its units stay listed. The same rule gates
 * the headline, so no aggregate from the headline to a drilled-in slice stands on a few
 * deployments counted as many points.
 */
import { aggregate, countRoleKeys, type FlatPoint } from './aggregate'
import { TOO_FEW, type Figure, type HeadlineBlock, type GradedGrade, type TooFew, type UnitIdentity } from './types'

/** min_points of the design (COV-13): distinct role keys, not points. Summaries publish it too. */
export const MIN_ROLE_KEYS = 10

export interface SliceAttr {
  id: string
  label: string
  /** The attribute's values on a point (several for substitutions, one otherwise). */
  values: (p: FlatPoint) => string[]
  /** Which field of a not-scored point carries the same attribute, for coverage. */
  notScored?: 'hardware'
}

const one = (f: (p: FlatPoint) => string | number | null | undefined) => (p: FlatPoint) => [String(f(p) ?? 'unknown')]
const month = (d?: string) => (d ? d.slice(0, 7) : 'unknown')

export const SLICE_ATTRS: SliceAttr[] = [
  { id: 'source', label: 'source', values: one((p) => (p.identity as Partial<UnitIdentity> | undefined)?.source ?? 'inferencex') },
  { id: 'model', label: 'model', values: one((p) => p.model) },
  { id: 'precision', label: 'precision', values: one((p) => p.precision) },
  { id: 'chip', label: 'chip', values: one((p) => p.gpu), notScored: 'hardware' },
  { id: 'engine', label: 'engine', values: one((p) => p.framework) },
  { id: 'engine_version', label: 'engine version', values: one((p) => p.engineVersion) },
  { id: 'engine_commit', label: 'engine commit', values: one((p) => p.fidelity?.build.commit) },
  { id: 'commit_distance', label: 'commit distance', values: one((p) => p.fidelity?.commit_distance?.state ?? 'none') },
  {
    id: 'topology', label: 'topology',
    values: one((p) => Object.entries(p.parallelism).sort(([a], [b]) => a.localeCompare(b)).map(([k, v]) => `${k}${v}`).join(' ')),
  },
  { id: 'serving', label: 'serving (aggregated or P/D pools)', values: one((p) => p.serving) },
  { id: 'spec_method', label: 'speculative method', values: one((p) => p.specMethod ?? 'none') },
  { id: 'workload', label: 'workload', values: one((p) => p.workloadLabel) },
  { id: 'benchmark_type', label: 'workload type', values: one((p) => p.identity?.benchmark_type) },
  { id: 'input_length', label: 'input length', values: one((p) => p.isl) },
  { id: 'output_length', label: 'output length', values: one((p) => p.osl) },
  { id: 'concurrency', label: 'concurrency', values: one((p) => p.concurrency) },
  { id: 'measured_month', label: 'measured month', values: one((p) => month(p.measuredDate)) },
  { id: 'grade', label: 'grade', values: one((p) => p.fidelity?.grade) },
  { id: 'run_release', label: 'release the run measured', values: one((p) => p.fidelity?.run_release) },
  {
    id: 'substitution', label: 'substitution',
    values: (p) => {
      const kinds = [...new Set((p.fidelity?.substitutions ?? []).map((s) => s.kind))]
      return kinds.length > 0 ? kinds : ['none']
    },
  },
]

/** Attributes COV-13 names that no point records in this snapshot yet; listed, not sliceable. */
export const UNRECORDED: { id: string; label: string }[] = [
  { id: 'node_count', label: 'node count' },
  { id: 'interconnect', label: 'interconnect' },
  { id: 'offload', label: 'offload and KV tiers' },
  { id: 'router', label: 'router' },
  { id: 'arrival', label: 'arrival process' },
  { id: 'prefix', label: 'prefix sharing' },
  { id: 'source_revision', label: 'source revision (dump or api)' },
]

export function sliceAttr(id: string | null | undefined): SliceAttr | null {
  return SLICE_ATTRS.find((a) => a.id === id) ?? null
}

export function inSlice(p: FlatPoint, by: string, value: string): boolean {
  return sliceAttr(by)?.values(p).includes(value) ?? false
}

export interface SliceRow {
  value: string
  points: number
  roleKeys: number
  /** Scored points over every measurement of the slice, where the not-scored points record the attribute. */
  coverage: { scored: number; total: number } | null
  ttft: number | TooFew | null
  tpot: number | TooFew | null
  shown: boolean
  reason: string | null
  /** The slice's units: its points' ids, listed whether or not an accuracy is shown. */
  units: string[]
}

export function suppressionReason(roleKeys: number, min: number): string {
  return `${roleKeys} role key${roleKeys === 1 ? '' : 's'}, fewer than the ${min} needed for an accuracy`
}

export function sliceBy(
  points: FlatPoint[],
  by: string,
  min: number,
  notScored: { hardware?: string }[] = [],
): SliceRow[] {
  const attr = sliceAttr(by)
  if (!attr) return []
  const groups = new Map<string, FlatPoint[]>()
  for (const p of points) {
    for (const v of attr.values(p)) {
      const g = groups.get(v)
      if (g) g.push(p)
      else groups.set(v, [p])
    }
  }
  const rows = [...groups.entries()].map(([value, pts]): SliceRow => {
    const m = aggregate(pts, 'all', min).mape
    const roleKeys = countRoleKeys(pts)
    const shown = roleKeys >= min
    const missed = attr.notScored ? notScored.filter((n) => n[attr.notScored!] === value).length : null
    return {
      value,
      points: pts.length,
      roleKeys,
      coverage: missed == null ? null : { scored: pts.length, total: pts.length + missed },
      ttft: m.ttft,
      tpot: m.tpot,
      shown,
      reason: shown ? null : suppressionReason(roleKeys, min),
      units: pts.map((p) => p.pointId ?? `${p.sweepKey}|${p.concurrency}`),
    }
  })
  return rows.sort((a, b) => b.points - a.points || a.value.localeCompare(b.value))
}

/**
 * The published headline gated by role keys. summary.json counts points (schema v3, frozen, COV-8);
 * the figure is kept only where the points under it span at least `min` role keys, overall and
 * for each grade, and its role-key count is added beside it.
 */
export function gateHeadline(h: HeadlineBlock, points: FlatPoint[], min: number): HeadlineBlock {
  const gate = (f: Figure, pts: FlatPoint[]): Figure => {
    const roleKeys = countRoleKeys(pts)
    return { ...f, mape: roleKeys < min ? TOO_FEW : f.mape, roleKeys }
  }
  const out: HeadlineBlock = {
    ...h,
    headline: { ttft: gate(h.headline.ttft, points), tpot: gate(h.headline.tpot, points) },
    grades: { ...h.grades },
  }
  for (const g of Object.keys(h.grades) as GradedGrade[]) {
    const pts = points.filter((p) => p.fidelity?.grade === g)
    const r = h.grades[g]
    const ttft = gate(r.ttft, pts)
    out.grades[g] = {
      ...r,
      ttft,
      tpot: gate(r.tpot, pts),
      share: countRoleKeys(pts) < min ? TOO_FEW : r.share,
    }
  }
  return out
}
