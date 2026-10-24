/**
 * The live view's latest-per-config rule (Discussion #15, Decided). The single-run Overview shows
 * only the newest measurement per config; Compare keeps all, so this helper must not be reachable
 * from the Compare path (it isn't — Compare calls flattenPoints directly).
 */
import { describe, expect, it } from 'vitest'
import { latestPerConfig, type FlatPoint } from './aggregate'

function pt(over: Partial<FlatPoint>): FlatPoint {
  return {
    model: 'm', modelVllm: null, workloadLabel: 'w', isl: null, osl: null, gpu: 'h100',
    precision: 'fp8', framework: 'vllm', engineVersion: null, isMultinode: false,
    topoLabel: 't', parallelism: {}, serving: null, specMethod: null, concurrency: 1,
    tier: 'all', measTtftMs: 1, measTpotMs: 1, predTtftMs: 1, predTpotMs: 1,
    errTtft: 0, errTpot: 0, shapeTtft: null, shapeTpot: null, shapeReason: null,
    sweepKey: 'm|w|h100|t', ...over,
  }
}

describe('latestPerConfig', () => {
  it('keeps only the newest measurement of one config', () => {
    const older = pt({ pointId: 'old', measuredDate: '2026-09-01' })
    const newer = pt({ pointId: 'new', measuredDate: '2026-10-01' })
    const live = latestPerConfig([older, newer])
    expect(live.map((p) => p.pointId)).toEqual(['new'])
  })

  it('keeps distinct configs (different concurrency) apart', () => {
    const c1 = pt({ pointId: 'a', measuredDate: '2026-10-01', concurrency: 1 })
    const c2 = pt({ pointId: 'b', measuredDate: '2026-10-01', concurrency: 2 })
    expect(latestPerConfig([c1, c2]).length).toBe(2)
  })

  it('keeps distinct deployments (different sweepKey) apart', () => {
    const a = pt({ pointId: 'a', measuredDate: '2026-10-01', sweepKey: 'm|w|h100|t1' })
    const b = pt({ pointId: 'b', measuredDate: '2026-10-01', sweepKey: 'm|w|h100|t2' })
    expect(latestPerConfig([a, b]).length).toBe(2)
  })

  it('breaks date ties by pointId, deterministically', () => {
    const a = pt({ pointId: 'zzz', measuredDate: '2026-10-01' })
    const b = pt({ pointId: 'aaa', measuredDate: '2026-10-01' })
    expect(latestPerConfig([a, b]).map((p) => p.pointId)).toEqual(['zzz'])
  })

  it('passes v1 points (no measuredDate) through untouched', () => {
    const a = pt({ pointId: undefined, measuredDate: undefined })
    const b = pt({ pointId: undefined, measuredDate: undefined, concurrency: 2 })
    expect(latestPerConfig([a, b]).length).toBe(2)
  })
})
