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

/** The v2 tier explanation, naming the snapshot's own build window: `ref` (the vLLM release
 *  BLIS is calibrated on) and `maxDistance` (how many commits from it still count as that
 *  build) come from the snapshot's provenance, never from here. */
export function tierV2Definition(ref: string, maxDistance: number): string {
  const n = maxDistance.toLocaleString('en-US')
  return (
    'Which points are included. “exact”: BLIS simulated exactly the configuration that was measured, ' +
    `on a vLLM build within ${n} commits of ${ref}, the release BLIS is calibrated on. ` +
    '“estimated”: one or more settings BLIS can’t represent yet were estimated, or the run’s ' +
    `vLLM build is more than ${n} commits from ${ref} or a custom build (marked ≈). “all”: both.`
  )
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
  tierV2: {
    label: 'tier',
    definition:
      'Which points are included. “exact”: BLIS simulated exactly the configuration that was measured, on a vLLM build close to the release BLIS is calibrated on. “estimated”: one or more settings BLIS can’t represent yet were estimated, or the run’s vLLM build is further from that release (marked ≈). “all”: both.',
  },

  coverage: {
    label: 'coverage',
    definition: 'How many points were scored vs. not. Nothing is hidden: unscored points are counted, and the reason for each is in the downloadable results.',
  },
  provenance: {
    label: 'match',
    definition:
      '✓ exact: BLIS simulated exactly what the run used. ≈ estimated: one or more settings BLIS can’t represent yet were replaced by the nearest ones it can, or the run used a different vLLM build; hover to see what differs.',
  },



  diff: {
    label: 'Δ (newer − older)',
    definition: 'The newer run minus the older run, over the points both runs scored. Green means the newer run is more accurate; red means it got worse.',
  },
}
