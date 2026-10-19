/**
 * Number formatting, mirroring inference-sim/leaderboard/web/src/format.ts so the two
 * dashboards read identically. A missing value is always an em dash — never "0.0%" or a
 * blank or a NaN (RFC B1): an unreported number must never read as a real zero.
 */

export const EM_DASH = '—'

/** Renders a 0..100 percent at fixed precision. null/non-finite → em dash. */
export function formatPct(value: number | null | undefined, digits = 1): string {
  if (value == null || !Number.isFinite(value)) return EM_DASH
  return `${value.toLocaleString('en-US', {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })}%`
}

/** A signed percent for per-point error: +19.3% / −6.9% (true minus sign). */
export function formatSignedPct(value: number | null | undefined, digits = 1): string {
  if (value == null || !Number.isFinite(value)) return EM_DASH
  const sign = value > 0 ? '+' : value < 0 ? '−' : ''
  const mag = Math.abs(value).toLocaleString('en-US', {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })
  return `${sign}${mag}%`
}

/**
 * A signed delta in percentage points for the A-vs-B compare view: +2.7 / −1.4 (true minus sign,
 * no "%" since it's a difference of two percentages — "pp"). null/non-finite → em dash. A delta of
 * exactly 0 renders "0.0" with no sign.
 */
export function formatSignedDelta(value: number | null | undefined, digits = 1): string {
  if (value == null || !Number.isFinite(value)) return EM_DASH
  const sign = value > 0 ? '+' : value < 0 ? '−' : ''
  const mag = Math.abs(value).toLocaleString('en-US', {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })
  return `${sign}${mag}`
}

/** Renders an absolute latency in ms. Reused convention from the leaderboard. */
export function formatMs(value: number | null | undefined, digits: number): string {
  if (value == null || !Number.isFinite(value)) return EM_DASH
  // Always milliseconds (the points-table columns are labelled "(ms)"), at a FIXED precision the
  // caller sets per column — so every cell down a column has the same decimals and a measured
  // value lines up with BLIS's prediction. (TTFT spans ~26–700,000 ms → 0 decimals; TPOT spans
  // ~2.5–465 ms → 2 decimals.) Thousands grouping for large values (2,245).
  return value.toLocaleString('en-US', { minimumFractionDigits: digits, maximumFractionDigits: digits })
}

/** Renders an integer count with thousands grouping. */
export function formatCount(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return EM_DASH
  return value.toLocaleString('en-US', { maximumFractionDigits: 0 })
}

/**
 * A vLLM version label. Numeric semver gets a "v" prefix (0.21.0 → "v0.21.0"); non-semver
 * build tags (nightly, custom images like "deepseekv4-cu130") are shown verbatim — no "v".
 */
export function formatVersion(v: string | null | undefined): string {
  if (!v) return EM_DASH
  const bare = v.replace(/^v/, '')
  return /^\d+\.\d+/.test(bare) ? `v${bare}` : v
}
