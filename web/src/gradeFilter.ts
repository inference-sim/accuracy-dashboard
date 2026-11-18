/**
 * The cumulative closeness-grade filter that replaced the tier toggle. A point is shown when its
 * grade is at or above the one named: G1 only, up to G2, up to G3, or every graded point. A v1
 * snapshot has no grades; it is read the way the tier was: measured_or_resolved is G1 and every
 * other point is in "all graded" only, so an old release shown in Compare still renders.
 */
import type { GradeFilter } from './route'

const LIMIT: Record<GradeFilter, number> = { G1: 1, G2: 2, G3: 3, all: 4 }

/** A point's grade as a number 1-4. */
export function gradeRank(p: { tier: string; fidelity?: { grade?: string } }): number {
  const g = p.fidelity?.grade
  if (g && /^G[1-4]$/.test(g)) return Number(g[1])
  return p.tier === 'measured_or_resolved' ? 1 : 4
}

export function inGrade(p: { tier: string; fidelity?: { grade?: string } }, filter: GradeFilter): boolean {
  return gradeRank(p) <= LIMIT[filter]
}

/** The labels of the control, in order. */
export const GRADE_LABELS: Record<GradeFilter, string> = { G1: 'G1', G2: 'up to G2', G3: 'up to G3', all: 'all graded' }
