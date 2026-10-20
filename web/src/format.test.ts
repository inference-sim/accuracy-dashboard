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

  it('formatMs renders ms at a fixed precision (no s/ms switch), thousands-grouped', () => {
    // The points table uses 2 decimals for both TTFT and TPOT.
    expect(formatMs(7.18, 2)).toBe('7.18')
    expect(formatMs(101.5255, 2)).toBe('101.53') // sub-ms precision kept, not rounded to int
    expect(formatMs(821, 2)).toBe('821.00')
    expect(formatMs(2245, 2)).toBe('2,245.00') // thousands grouping, never "2.25s"
    expect(formatMs(708765.4, 2)).toBe('708,765.40')
    expect(formatMs(null, 2)).toBe(EM_DASH)
  })

  it('formatCount groups thousands and em-dashes null', () => {
    expect(formatCount(1584)).toBe('1,584')
    expect(formatCount(null)).toBe(EM_DASH)
  })
})
