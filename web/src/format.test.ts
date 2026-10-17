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

  it('formatMs scales ms→s and keeps small decode numbers readable', () => {
    expect(formatMs(7.18)).toBe('7.18')
    expect(formatMs(821)).toBe('821')
    expect(formatMs(1500)).toBe('1.50s')
    expect(formatMs(null)).toBe(EM_DASH)
  })

  it('formatCount groups thousands and em-dashes null', () => {
    expect(formatCount(1584)).toBe('1,584')
    expect(formatCount(null)).toBe(EM_DASH)
  })
})
