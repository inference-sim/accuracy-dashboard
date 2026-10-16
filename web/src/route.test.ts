import { describe, expect, it } from 'vitest'
import { DEFAULT_ROUTE, parseRoute, routeToHash } from './route'

describe('deep-link round-trips (RFC B3)', () => {
  it('defaults: no sel, measured_or_resolved tier, on-target vllm, multinode off', () => {
    expect(parseRoute('#/')).toEqual(DEFAULT_ROUTE)
    expect(parseRoute('')).toEqual(DEFAULT_ROUTE)
  })

  it('round-trips a selected row + tier + filters', () => {
    const state = { sel: 'minimax-m3|1024:1024|H200|tp8', tier: 'all' as const, vllm: 'all' as const, multinode: true }
    const hash = routeToHash(state)
    expect(parseRoute(hash)).toEqual(state)
  })

  it('encodes a sel with reserved characters', () => {
    const state = { sel: 'a model|w & co|H200|tp8·ep8', tier: 'measured_or_resolved' as const, vllm: 'on-target' as const, multinode: false }
    const hash = routeToHash(state)
    expect(parseRoute(hash).sel).toBe(state.sel)
  })

  it('a bare default state produces #/ (no query noise)', () => {
    expect(routeToHash(DEFAULT_ROUTE)).toBe('#/')
  })
})
