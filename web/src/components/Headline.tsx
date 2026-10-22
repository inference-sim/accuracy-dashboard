/**
 * The answer first (#23): the two numbers a visitor came for, large, with one line of context.
 * Computed from the same visible points as the tables, so a filter changes it too (RFC B3).
 */
import { formatCount, formatPct } from '../format'
import type { MetricBlockPair, TierKey } from '../types'

interface Props {
  totals: MetricBlockPair
  tier: TierKey
  points: number
  models: number
  blisRelease: string | null
  dataDate: string | null
}

function Stat({ value, label, hint }: { value: number | null; label: string; hint: string }) {
  return (
    <div className="stat">
      <div className="stat-value">{formatPct(value)}</div>
      <div className="stat-label">{label}</div>
      <div className="stat-hint">{hint}</div>
    </div>
  )
}

export function Headline({ totals, tier, points, models, blisRelease, dataDate }: Props) {
  const t = totals[tier]
  return (
    <section className="headline" aria-label="Overall accuracy">
      <div className="stats">
        <Stat value={t.mape.ttft} label="Time to first token" hint="average error" />
        <Stat value={t.mape.tpot} label="Time per output token" hint="average error" />
      </div>
      <p className="context">
        {formatCount(points)} measurements · {models} models
        {blisRelease && <> · BLIS {blisRelease}</>}
        {dataDate && <> · InferenceX data from {dataDate}</>}
        <span className="lower"> · lower is better</span>
      </p>
    </section>
  )
}
