/**
 * The answer first (#23): the two numbers a visitor came for, large, with one line of context.
 * v1 and v2 compute them from the points; v3 publishes them (design §11.3, COV-11): the accuracy
 * over every graded point, G1 to G4, and beside it each grade's share and own accuracy, every
 * figure with its point count, and "too few points" for a figure under the summary's minimum.
 */
import { formatCount, formatPct } from '../format'
import type { Figure, HeadlineBlock, MetricBlockPair, TierKey } from '../types'

interface Props {
  totals: MetricBlockPair
  tier: TierKey
  points: number
  models: number
  blisRelease: string | null
  dataDate: string | null
  /** v2 (API ingest): the oldest and newest measurement dates among the points, and when the
   *  API was pulled. Shown instead of `dataDate`, which for v1 is the database dump's date. */
  measuredRange?: { from: string; to: string } | null
  pulledAt?: string | null
  /** v2: how many of the points are exact and how many estimated. The headline averages both
   *  (the "all" tier), so it says so next to the count. */
  split?: { exact: number; estimated: number } | null
  /** v3: the published headline and grade split. When given, the numbers come from it. */
  graded?: HeadlineBlock | null
}

const GRADE_LABEL: Record<string, string> = {
  G1: 'exact',
  G2: 'estimated',
  G3: 'other release, same code',
  G4: 'other release or build',
}

/** A published figure: a percentage, or "too few points" under the summary's minimum. */
function figureText(f: Figure): string {
  return f.mape === 'too few points' ? 'too few points' : formatPct(f.mape)
}

function FigureStat({ figure, label }: { figure: Figure; label: string }) {
  return (
    <div className="stat">
      <div className="stat-value">{figureText(figure)}</div>
      <div className="stat-label">{label}</div>
      <div className="stat-hint">
        average error · {formatCount(figure.n)} point{figure.n === 1 ? '' : 's'}
      </div>
    </div>
  )
}

/** v3: each graded grade's share of the graded points, its count and its own accuracy. */
function GradeSplit({ h }: { h: HeadlineBlock }) {
  return (
    <table className="grades" aria-label="accuracy by grade">
      <thead>
        <tr>
          <th scope="col">grade</th>
          <th scope="col">points</th>
          <th scope="col">share</th>
          <th scope="col">TTFT error</th>
          <th scope="col">TPOT error</th>
        </tr>
      </thead>
      <tbody>
        {(['G1', 'G2', 'G3', 'G4'] as const).map((g) => {
          const r = h.grades[g]
          return (
            <tr key={g}>
              <th scope="row">
                {g} <span className="facet">{GRADE_LABEL[g]}</span>
              </th>
              <td>{formatCount(r.points)}</td>
              <td>{r.share == null ? '—' : formatPct(r.share * 100)}</td>
              <td>{figureText(r.ttft)}</td>
              <td>{figureText(r.tpot)}</td>
            </tr>
          )
        })}
      </tbody>
    </table>
  )
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

export function Headline({ totals, tier, points, models, blisRelease, dataDate, measuredRange, pulledAt, split, graded }: Props) {
  const t = totals[tier]
  return (
    <section className="headline" aria-label="Overall accuracy">
      {graded ? (
        <div className="stats">
          <FigureStat figure={graded.headline.ttft} label="Mean time to first token, G1 to G4" />
          <FigureStat figure={graded.headline.tpot} label="Mean time per output token, G1 to G4" />
        </div>
      ) : (
        <div className="stats">
          <Stat value={t.mape.ttft} label="Mean time to first token" hint="average error" />
          <Stat value={t.mape.tpot} label="Mean time per output token" hint="average error" />
        </div>
      )}
      {graded && <GradeSplit h={graded} />}
      <p className="context">
        {graded ? (
          <>
            {formatCount(graded.graded)} graded of {formatCount(graded.points)} measurement
            {graded.points === 1 ? '' : 's'}, {formatCount(graded.not_scored)} not scored
          </>
        ) : (
          <>
            {formatCount(points)} measurement{points === 1 ? '' : 's'}
          </>
        )}
        {split && split.estimated > 0 && (
          <> ({formatCount(split.exact)} exact, {formatCount(split.estimated)} estimated)</>
        )}{' '}
        · {models} model{models === 1 ? '' : 's'}
        {blisRelease && <> · BLIS {blisRelease}</>}
        {measuredRange ? (
          <>
            {' '}· InferenceX data range{' '}
            {measuredRange.from === measuredRange.to ? measuredRange.to : `${measuredRange.from} to ${measuredRange.to}`}
            {pulledAt && <> · API pull date {pulledAt.slice(0, 10)}</>}
          </>
        ) : (
          dataDate && <> · InferenceX data from {dataDate}</>
        )}
        <span className="lower"> · lower is better</span>
      </p>
    </section>
  )
}
