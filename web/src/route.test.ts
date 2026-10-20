import { describe, expect, it } from 'vitest'
import { DEFAULT_ROUTE, parseRoute, routeToHash } from './route'

describe('deep-link round-trips (RFC B3)', () => {
  it('defaults: no sel, measured_or_resolved tier, all vllm, multinode off', () => {
    expect(parseRoute('#/')).toEqual(DEFAULT_ROUTE)
    expect(parseRoute('')).toEqual(DEFAULT_ROUTE)
  })

  it('round-trips a selected row + tier + a pinned vLLM version', () => {
    const state = { run: '2026-10-16_blis-v0.10.0_ix-2026-09-28', runB: null, sel: 'minimax-m3|1024:1024|H200|tp8', tier: 'all' as const, vllm: { version: '0.29.0' }, multinode: true }
    const hash = routeToHash(state)
    expect(parseRoute(hash)).toEqual(state)
  })

  it('encodes a sel with reserved characters', () => {
    const state = { run: null, runB: null, sel: 'a model|w & co|H200|tp8·ep8', tier: 'measured_or_resolved' as const, vllm: 'all' as const, multinode: false }
    const hash = routeToHash(state)
    expect(parseRoute(hash).sel).toBe(state.sel)
  })

  it('round-trips a two-run (A-vs-B) compare state', () => {
    const state = { run: '2026-10-18_blis-v0.10.0_ix-2026-09-28', runB: '2026-10-19_blis-v0.10.1_ix-2026-09-28', sel: null, tier: 'all' as const, vllm: 'all' as const, multinode: false }
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
})
