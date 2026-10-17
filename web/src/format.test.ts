import { describe, expect, it } from 'vitest'
import { EM_DASH, formatCount, formatMs, formatPct, formatSignedPct } from './format'

describe('format helpers never show NaN/blank (RFC B1)', () => {
  it('formatPct renders em dash for null/non-finite', () => {
    expect(formatPct(null)).toBe(EM_DASH)
    expect(formatPct(undefined)).toBe(EM_DASH)
    expect(formatPct(NaN)).toBe(EM_DASH)
    expect(formatPct(20.1)).toBe('20.1%')
  })

  it('formatSignedPct uses a true minus sign and + for positive', () => {
    expect(formatSignedPct(19.3)).toBe('+19.3%')
    expect(formatSignedPct(-6.9)).toBe('−6.9%')
    expect(formatSignedPct(0)).toBe('0.0%')
    expect(formatSignedPct(null)).toBe(EM_DASH)
  })

  it('formatMs renders ms at a fixed per-column precision (no s/ms switch)', () => {
    // TPOT column: 2 decimals; every cell matches
    expect(formatMs(7.18, 2)).toBe('7.18')
    expect(formatMs(465.4, 2)).toBe('465.40')
    // TTFT column: 0 decimals, thousands grouping, never "1.50s"
    expect(formatMs(821, 0)).toBe('821')
    expect(formatMs(2245, 0)).toBe('2,245')
    expect(formatMs(708765, 0)).toBe('708,765')
    expect(formatMs(null, 0)).toBe(EM_DASH)
  })

  it('formatCount groups thousands and em-dashes null', () => {
    expect(formatCount(1584)).toBe('1,584')
    expect(formatCount(null)).toBe(EM_DASH)
  })
})
