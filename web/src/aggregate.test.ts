/**
 * TypeScript self-consistency oracle (PR #3 review T-a): the Python oracle in build_summary.py
 * re-derives over its own in-memory list and never touches aggregate.ts. These assert that the
 * CLIENT recompute (flattenPoints → aggregatePair) matches the stored totals the orchestrator
 * wrote, for both tiers and at a node level — the "filters never show stale numbers" guarantee
 * (RFC B3) is only true if the two implementations agree.
 */
import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { validateSummary } from './load'
import { aggregate, aggregatePair, flattenPoints, type FlatPoint } from './aggregate'
import type { Summary } from './types'

function loadFixture(): Summary {
  const path = fileURLToPath(new URL('../testdata/render-fixture.summary.json', import.meta.url))
  return validateSummary(JSON.parse(readFileSync(path, 'utf8')))
}

const close = (a: number | null, b: number | null, eps = 1e-6) => {
  if (a == null && b == null) return true
  if (a == null || b == null) return false
  return Math.abs(a - b) <= eps * Math.max(1, Math.abs(a), Math.abs(b))
}

describe('client recompute matches the orchestrator-stored totals (T-a oracle)', () => {
  it('aggregatePair(flattenPoints(summary)) ≈ summary.totals, both tiers', () => {
    const s = loadFixture()
    const got = aggregatePair(flattenPoints(s))
    for (const tier of ['measured_or_resolved', 'all'] as const) {
      for (const kind of ['mape', 'shape'] as const) {
        for (const m of ['ttft', 'tpot'] as const) {
          expect(close(got[tier][kind][m], s.totals[tier][kind][m])).toBe(true)
        }
      }
    }
  })

  it('a model node recomputes to its stored metrics (per-node check)', () => {
    const s = loadFixture()
    const all = flattenPoints(s)
    for (const model of s.matrix.slice(0, 2)) {
      const pts = all.filter((p) => p.model === model.model)
      const got = aggregatePair(pts)
      for (const tier of ['measured_or_resolved', 'all'] as const) {
        expect(close(got[tier].mape.ttft, model.metrics[tier].mape.ttft)).toBe(true)
        expect(close(got[tier].mape.tpot, model.metrics[tier].mape.tpot)).toBe(true)
      }
    }
  })

  it('point-level averaging ≠ mean-of-child-means (the thing the roll-up gets right)', () => {
    // Two child groups of unequal size. mean-of-points weights by count; mean-of-child-means does
    // not. A correct aggregate uses point-level averaging, so the two must differ here.
    const mk = (errTtft: number): FlatPoint => ({
      model: 'm', modelVllm: null, workloadLabel: 'w', isl: 1, osl: 1, gpu: 'g', precision: null,
      framework: 'vllm', engineVersion: null, isMultinode: false, topoLabel: 't', parallelism: {},
      serving: null, specMethod: null, concurrency: 1, tier: 'all',
      measTtftMs: 1, measTpotMs: 1, predTtftMs: 1, predTpotMs: 1,
      errTtft, errTpot: 0, shapeTtft: null, shapeTpot: null, shapeReason: null, sweepKey: 'm|w|g|t',
    })
    // group A: 3 points of error 30 ; group B: 1 point of error 90
    const pts = [mk(30), mk(30), mk(30), mk(90)]
    const pointLevel = aggregate(pts, 'all').mape.ttft! // |mean| over 4 points = (30*3+90)/4 = 45
    const childMeanA = 30
    const childMeanB = 90
    const meanOfChildMeans = (childMeanA + childMeanB) / 2 // = 60
    expect(close(pointLevel, 45)).toBe(true)
    expect(close(meanOfChildMeans, 60)).toBe(true)
    expect(pointLevel).not.toBe(meanOfChildMeans) // point-level averaging is NOT mean-of-means
  })
})
