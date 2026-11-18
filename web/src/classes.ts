/**
 * The classes page's data (data/latest/classes.json, built by orchestrator/build_classes.py; docs/m3/classes/README.md).
 * Each class of points has its own counts, grade mix and accuracy by grade; classes are never added into one another.
 * Validation is loud, like the summary's: a wrong format or a malformed class throws a clear message.
 */
export const CLASSES_URL = 'data/latest/classes.json'
export const CLASSES_FORMAT = 'classes-1'
export const TOO_FEW = 'too few points'

export type ClassKind = 'regular' | 'reconstructed' | 'provisional'
export type ClassStat = 'ttft' | 'tpot' | 'itl'
export const CLASS_GRADES = ['G1', 'G2', 'G3', 'G4', 'G5'] as const
export const GRADED = ['G1', 'G2', 'G3', 'G4'] as const

export interface ClassFigure {
  n: number
  mape: number | typeof TOO_FEW
  signed_median: number | typeof TOO_FEW | null
}
export interface ClassCounts {
  points: number
  scored: number
  refused: number
  failed: number
  withheld: number
}
export interface ClassEntry {
  id: string
  label: string
  kind: ClassKind
  /** true while the class's file is from a census that is not the final one. */
  interim: boolean
  note: string
  counts: ClassCounts
  grades: Record<(typeof CLASS_GRADES)[number], number>
  accuracy_by_grade: Record<string, Partial<Record<ClassStat, ClassFigure>>>
  refusals: { code: string; subject: string; points: number }[]
  substitutions: { kind: string; subject: string; detail: string; points: number }[]
  engines?: { engine: string; points: number; graded: number; grades: Record<string, number>; note?: string }[]
  /** The partition the class's points were scored on (configiq: train and validation; the test partition is withheld). */
  partition?: string
  /** A statistic not shown as an accuracy figure, with the sentence shown instead (stat -> reason). */
  figure_notes?: Partial<Record<ClassStat, string>>
  /** One plain line that stands for the rows that are not scored; the card then lists no refusal. */
  plain_line?: string
  by_model?: { model: string; scored: number; gap: string | null; accuracy: Partial<Record<ClassStat, ClassFigure>> }[]
  itl_streamed_in_chunks_left_out?: number
  provenance: { command: string; heads: Record<string, unknown>; pulled_at: string; derived_at?: string; dataset?: string; split?: string }
}
export interface ClassesDoc {
  format: typeof CLASSES_FORMAT
  generated_at: string
  snapshot_id: string | null
  classes: ClassEntry[]
}

export class ClassesLoadError extends Error {}

const KINDS = ['regular', 'reconstructed', 'provisional']

export function validateClasses(raw: unknown): ClassesDoc {
  if (raw == null || typeof raw !== 'object') throw new ClassesLoadError('classes.json is not a JSON object')
  const doc = raw as Record<string, unknown>
  if (doc.format !== CLASSES_FORMAT) {
    throw new ClassesLoadError(`classes.json format is ${JSON.stringify(doc.format)}, this build renders ${CLASSES_FORMAT}`)
  }
  if (!Array.isArray(doc.classes) || doc.classes.length === 0) throw new ClassesLoadError('classes.json holds no classes')
  for (const c of doc.classes as Record<string, unknown>[]) {
    const id = String(c?.id)
    for (const k of ['label', 'kind', 'counts', 'grades', 'accuracy_by_grade', 'provenance']) {
      if (c == null || !(k in c)) throw new ClassesLoadError(`classes.json class ${id} lacks "${k}"`)
    }
    if (!KINDS.includes(String(c.kind))) throw new ClassesLoadError(`classes.json class ${id} has the unknown kind ${JSON.stringify(c.kind)}`)
  }
  return raw as ClassesDoc
}

/** The plain-words tag shown beside a class's name, so a reconstructed or provisional class can never read as a regular one. */
export function kindTag(kind: ClassKind): string | null {
  if (kind === 'reconstructed') return 'reconstructed recipe, G4'
  if (kind === 'provisional') return 'provisional, capped at G3, outside the headline'
  return null
}

/** The statistics a class reports, in column order: a statistic only when some grade has a figure for it (configiq has no TTFT figure; most classes have no ITL). */
export function statsOf(c: ClassEntry): ClassStat[] {
  return (['ttft', 'tpot', 'itl'] as ClassStat[]).filter((s) => Object.values(c.accuracy_by_grade).some((g) => g[s]))
}

/** The Classes tab fetches classes.json only when it is open, once, and only in a browser: not while a document or an error is already held. */
export function shouldFetchClasses(view: string, doc: ClassesDoc | null, error: string | null, inBrowser: boolean): boolean {
  return view === 'classes' && doc == null && error == null && inBrowser
}

/** Fetch and validate classes.json. A non-OK answer or an invalid file throws a message the tab shows as it is. */
export async function fetchClasses(fetcher: typeof fetch = fetch, url: string = CLASSES_URL): Promise<ClassesDoc> {
  const r = await fetcher(url, { cache: 'no-cache' })
  if (!r.ok) throw new ClassesLoadError(`${url} answered ${r.status}: the classes are not published for this site yet`)
  return validateClasses(await r.json())
}
