import { describe, expect, it } from 'vitest'
import { DEFAULT_ROUTE, parseRoute, routeToHash } from './route'

describe('deep-link round-trips (RFC B3)', () => {
  it('defaults: no sel, every graded point, multinode off', () => {
    expect(parseRoute('#/')).toEqual(DEFAULT_ROUTE)
    expect(parseRoute('')).toEqual(DEFAULT_ROUTE)
  })

  it('round-trips a selected row + grade + multinode', () => {
    const state = { view: 'overview' as const, run: '2026-10-16_blis-v0.10.0_ix-2026-09-28', runB: null, sel: 'minimax-m3|1024:1024|H200|tp8', grade: 'G2' as const, multinode: true, by: null, sv: null }
    const hash = routeToHash(state)
    expect(parseRoute(hash)).toEqual(state)
  })

  it('ignores an old link\'s vLLM version filter (the filter was removed)', () => {
    expect(parseRoute('#/?tier=all&vllm=v%3A0.29.0')).toEqual({ ...DEFAULT_ROUTE, grade: 'all' })
  })

  it('encodes a sel with reserved characters', () => {
    const state = { view: 'overview' as const, run: null, runB: null, sel: 'a model|w & co|H200|tp8·ep8', grade: 'G1' as const, multinode: false, by: null, sv: null }
    const hash = routeToHash(state)
    expect(parseRoute(hash).sel).toBe(state.sel)
  })

  it('round-trips a two-run (A-vs-B) compare state', () => {
    const state = { view: 'dev' as const, run: '2026-10-18_blis-v0.10.0_ix-2026-09-28', runB: '2026-10-19_blis-v0.10.1_ix-2026-09-28', sel: null, grade: 'all' as const, multinode: false, by: null, sv: null }
    const hash = routeToHash(state)
    expect(hash).toContain('runB=')
    expect(parseRoute(hash)).toEqual(state)
  })

  it('omits runB from the hash when absent (single-run deep-links unchanged)', () => {
    const hash = routeToHash({ ...DEFAULT_ROUTE, run: '2026-10-19_blis-v0.10.0_ix-2026-09-28' })
    expect(hash).not.toContain('runB')
    expect(parseRoute(hash).runB).toBeNull()
  })

  it('a bare default state produces #/ (no query noise)', () => {
    expect(routeToHash(DEFAULT_ROUTE)).toBe('#/')
  })

  it('reads an old ?tier= link as a grade and writes it back as ?grade=', () => {
    expect(parseRoute('#/?tier=measured_or_resolved').grade).toBe('G1')
    expect(parseRoute('#/?tier=all').grade).toBe('all')
    expect(parseRoute('#/?tier=estimated').grade).toBe('all')
    expect(routeToHash(parseRoute('#/?sel=a&tier=measured_or_resolved'))).toBe('#/?sel=a&grade=G1')
    expect(routeToHash(parseRoute('#/?tier=all'))).toBe('#/')
  })

  it('a grade in the link wins over a tier in the same link', () => {
    expect(parseRoute('#/?grade=G3&tier=measured_or_resolved').grade).toBe('G3')
  })
})
