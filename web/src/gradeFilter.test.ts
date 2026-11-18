import { describe, expect, it } from 'vitest'
import { gradeRank, inGrade } from './gradeFilter'

const pt = (grade: string | undefined, tier = 'all') => ({ tier, fidelity: grade ? { grade } : undefined })

describe('the cumulative grade filter', () => {
  const points = [pt('G1', 'measured_or_resolved'), pt('G2'), pt('G3'), pt('G4')]
  const kept = (f: 'G1' | 'G2' | 'G3' | 'all') => points.filter((p) => inGrade(p, f)).map((p) => p.fidelity!.grade)

  it('keeps the grades at or above the one named, and every graded point on all', () => {
    expect(kept('G1')).toEqual(['G1'])
    expect(kept('G2')).toEqual(['G1', 'G2'])
    expect(kept('G3')).toEqual(['G1', 'G2', 'G3'])
    expect(kept('all')).toEqual(['G1', 'G2', 'G3', 'G4'])
  })

  it('reads a v1 point, which has no grade, as the tier did: measured_or_resolved is G1, the rest is in all only', () => {
    expect(gradeRank(pt(undefined, 'measured_or_resolved'))).toBe(1)
    expect(inGrade(pt(undefined, 'measured_or_resolved'), 'G1')).toBe(true)
    expect(inGrade(pt(undefined, 'all'), 'G3')).toBe(false)
    expect(inGrade(pt(undefined, 'all'), 'all')).toBe(true)
  })
})
