/**
 * One-sentence definitions for the core metric terms, surfaced as hover/focus tooltips (<Term>).
 * Grounded in the RFC / cmd/metricscore semantics — the same definitions the points-table note and
 * build_summary use. Scope is deliberately the core metrics only (MAPE, shape, TTFT, TPOT, tier);
 * facets/coverage terms are a possible later addition.
 */
export interface GlossaryEntry {
  /** the visible label (matches what already renders, so existing assertions/UX are unchanged) */
  label: string
  /** the tooltip body — one plain sentence */
  definition: string
}

export const GLOSSARY: Record<string, GlossaryEntry> = {
  mape: {
    label: 'error',
    definition:
      'Average error (mean absolute percentage error, MAPE): on average, how far BLIS’s predicted latency is from the measured one. Measured 100 ms, predicted 120 ms → 20%. Lower is better.',
  },
  shape: {
    label: 'trend',
    definition:
      'Trend error (shape): does BLIS get the trend right as load grows? Compares how latency rises with concurrency, ignoring a constant offset. If BLIS is always 20% high, trend error is 0. Lower is better.',
  },
  ttft: {
    label: 'TTFT',
    definition: 'Time to first token — how long until the first output token appears.',
  },
  tpot: {
    label: 'TPOT',
    definition: 'Time per output token — the average time between output tokens.',
  },
  tier: {
    label: 'tier',
    definition:
      'Which points are included. “measured·resolved” keeps only apples-to-apples comparisons — where BLIS ran the same configuration that was actually measured. “all” also includes points where that match is only approximate.',
  },
  coverage: {
    label: 'coverage',
    definition: 'How many points were scored vs. not. Nothing is hidden — unscored points are counted and the reasons shown.',
  },
  diff: {
    label: 'Δ (newer − older)',
    definition: 'The newer run minus the older run, over the points both runs scored. Green means the newer run is more accurate; red means it got worse.',
  },
}
