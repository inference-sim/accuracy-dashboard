/**
 * The sources page's data (data/latest/funnel.json, written by orchestrator/baseline/funnel.py, format funnel-2): for each anchor
 * source its funnel (units, in scope, scored), the scored count, the reason of every unscored unit, and for InferenceX the
 * vLLM and SGLang lanes apart; the training-only sources as labelled training diagnostics (never accuracy); and where
 * ledger.yaml disagrees with design D9. Validation is loud, like the summary's.
 */
export const FUNNEL_URL = 'data/latest/funnel.json'
export const FUNNEL_FORMAT = 'funnel-2'

export interface FunnelStages {
  rows_held: number
  units: number
  in_scope: number
  /** null when no probe was run (a floor, never a ceiling). */
  recoverable: number | null
  scored: number
}
export interface FunnelLane {
  stages: FunnelStages
  excluded: Record<string, number>
  scored_by_grade: Record<string, number>
  provisional: { units: number; by_grade: Record<string, number> }
  g5: Record<string, number>
  failed: Record<string, number>
  no_outcome: Record<string, number>
}
export interface Funnel extends FunnelLane {
  source: string
  role: 'anchor'
  anchor_rule: string
  not_anchor: Record<string, number>
  not_recovered: Record<string, number>
  withheld: Record<string, number>
  left_out_rows: Record<string, number>
  unresolved: { units: number; unit_ids: string[] }
  lanes?: Record<string, Pick<FunnelLane, 'stages' | 'excluded' | 'scored_by_grade' | 'provisional' | 'g5' | 'failed' | 'no_outcome'>>
}
export interface TrainingFunnel {
  source: string
  role: 'training-only'
  label: string
  stages: { rows_held: number; units: number }
  duplicates: number
  left_out_rows: Record<string, number>
}
export interface Discrepancy {
  source: string
  code: string
  text: string
}
export interface FunnelDoc {
  format: typeof FUNNEL_FORMAT
  funnels: Record<string, Funnel>
  scored: Record<string, number>
  training: Record<string, TrainingFunnel>
  cut_points: { checked: boolean; discrepancies: Discrepancy[] }
  problems: string[]
  meaning: string
}

export class FunnelLoadError extends Error {}

export function validateFunnel(raw: unknown): FunnelDoc {
  if (raw == null || typeof raw !== 'object') throw new FunnelLoadError('funnel.json is not a JSON object')
  const doc = raw as Record<string, unknown>
  if (doc.format !== FUNNEL_FORMAT) {
    throw new FunnelLoadError(`funnel.json format is ${JSON.stringify(doc.format)}, this build renders ${FUNNEL_FORMAT}`)
  }
  const funnels = doc.funnels as Record<string, Record<string, unknown>> | undefined
  if (funnels == null || typeof funnels !== 'object' || Object.keys(funnels).length === 0) {
    throw new FunnelLoadError('funnel.json holds no funnels')
  }
  for (const [name, f] of Object.entries(funnels)) {
    for (const k of ['stages', 'anchor_rule', 'scored_by_grade', 'g5', 'failed', 'no_outcome', 'excluded']) {
      if (f == null || !(k in f)) throw new FunnelLoadError(`funnel.json funnel ${name} lacks "${k}"`)
    }
  }
  for (const [name, t] of Object.entries((doc.training ?? {}) as Record<string, Record<string, unknown>>)) {
    // A training-only source is never accuracy: a file that gives one a scored count is refused, not shown.
    if (t.role !== 'training-only' || 'scored' in ((t.stages as object) ?? {}) || 'accuracy' in t) {
      throw new FunnelLoadError(`funnel.json training source ${name} must be training-only and carry no scored count or accuracy`)
    }
  }
  const cp = doc.cut_points as { checked?: boolean; discrepancies?: unknown } | undefined
  if (cp == null || typeof cp.checked !== 'boolean' || !Array.isArray(cp.discrepancies)) {
    throw new FunnelLoadError('funnel.json lacks cut_points (whether ledger.yaml was checked against D9, and what disagreed)')
  }
  return raw as FunnelDoc
}

/** The reason of every unit that is in scope and not scored, largest first: G5 (by code), failed, withheld and no result. */
export function unscoredReasons(f: Pick<FunnelLane, 'g5' | 'failed' | 'no_outcome'> & { withheld?: Record<string, number> }): { part: string; reason: string; units: number }[] {
  const rows = (part: string, d: Record<string, number> | undefined) =>
    Object.entries(d ?? {}).map(([reason, units]) => ({ part, reason, units }))
  return [...rows('G5', f.g5), ...rows('failed', f.failed), ...rows('withheld', f.withheld), ...rows('no result', f.no_outcome)].sort(
    (a, b) => b.units - a.units || a.part.localeCompare(b.part) || a.reason.localeCompare(b.reason),
  )
}

export function shouldFetchFunnel(view: string, doc: FunnelDoc | null, error: string | null, inBrowser: boolean): boolean {
  return view === 'sources' && doc == null && error == null && inBrowser
}

export async function fetchFunnel(fetcher: typeof fetch = fetch, url: string = FUNNEL_URL): Promise<FunnelDoc> {
  const r = await fetcher(url, { cache: 'no-cache' })
  if (!r.ok) throw new FunnelLoadError(`${url} answered ${r.status}: the per-source funnels are not published for this site yet`)
  return validateFunnel(await r.json())
}
