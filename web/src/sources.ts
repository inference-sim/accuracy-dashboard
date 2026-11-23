/**
 * The sources page's data (data/latest/funnel.json, written by orchestrator/baseline/funnel.py, format funnel-2): for each anchor
 * source its funnel (units, in scope, scored), the scored count, the reason of every unscored unit, and for InferenceX the
 * vLLM and SGLang lanes apart. The file also carries training-only sources and a ledger cut-point check; the page shows neither.
 * Validation is loud, like the summary's.
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
  /** Present in funnel.json, never shown: a training-only source has no accuracy and no place on the page. */
  training?: Record<string, TrainingFunnel>
  cut_points?: { checked: boolean; discrepancies: Discrepancy[] }
  problems: string[]
  meaning: string
}

export class FunnelLoadError extends Error {}
/** The site publishes no funnel.json (a 404, or a host that answers a missing path with the page): not a fault of the data. */
export class FunnelNotPublished extends FunnelLoadError {}

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
  return raw as FunnelDoc
}

/** One row of the Sources table: a source, or one engine lane of it (`lane` set, `role` null). */
export interface SourceRow {
  id: string
  source: string
  lane: string | null
  role: string | null
  stages: FunnelStages
  scored_by_grade: Record<string, number>
  g5: Record<string, number>
  failed: Record<string, number>
  no_outcome: Record<string, number>
  withheld?: Record<string, number>
}

/** The table's rows from the document: each source in the order it is published, its lanes right after it. */
export function sourceRows(doc: FunnelDoc): SourceRow[] {
  return Object.values(doc.funnels).flatMap((f) => [
    { id: f.source, source: f.source, lane: null, role: f.role, stages: f.stages, scored_by_grade: f.scored_by_grade, g5: f.g5, failed: f.failed, no_outcome: f.no_outcome, withheld: f.withheld },
    ...Object.entries(f.lanes ?? {}).map(([lane, l]) => ({
      id: `${f.source}/${lane}`, source: f.source, lane, role: null, stages: l.stages, scored_by_grade: l.scored_by_grade, g5: l.g5, failed: l.failed, no_outcome: l.no_outcome,
    })),
  ])
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
  if (!r.ok) throw new FunnelNotPublished(`${url} answered ${r.status}: the per-source funnels are not published for this site yet`)
  let raw: unknown
  try {
    raw = await r.json()
  } catch {
    // A static host that answers a missing path with index.html: the body is not JSON.
    throw new FunnelNotPublished(`${url} is not JSON: the per-source funnels are not published for this site yet`)
  }
  return validateFunnel(raw)
}
