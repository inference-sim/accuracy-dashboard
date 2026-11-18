/**
 * The classes page (data/latest/classes.json; docs/m3/classes/README.md): every class is its own card with its own counts, a
 * reconstructed or provisional class carries its tag, a figure under the minimum reads "too few points", and the page never adds
 * one class's points into another's. The inputs are synthetic (X12); the committed classes.json is also validated and rendered.
 */
import { describe, expect, it, vi } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { App } from './App'
import { Classes } from './components/Classes'
import { ClassesLoadError, validateClasses, type ClassEntry, type ClassesDoc } from './classes'
import { parseRoute, routeToHash } from './route'

const fig = (n: number, mape: number | 'too few points', med: number | 'too few points' | null = null) => ({ n, mape, signed_median: med })
const none = { ttft: fig(0, 'too few points'), tpot: fig(0, 'too few points') }

function entry(over: Partial<ClassEntry>): ClassEntry {
  return {
    id: 'x',
    label: 'X',
    kind: 'regular',
    interim: false,
    note: 'a note',
    counts: { points: 10, scored: 4, refused: 6, failed: 0, withheld: 0 },
    grades: { G1: 0, G2: 0, G3: 0, G4: 4, G5: 6 },
    accuracy_by_grade: { G1: none, G2: none, G3: none, G4: { ttft: fig(4, 'too few points'), tpot: fig(4, 'too few points') } },
    refusals: [{ code: 'field_not_modelled', subject: 'moe_runner_backend', points: 6 }],
    substitutions: [],
    provenance: { command: 'make it', heads: { harness: 'abcdef0123456789abcdef' }, pulled_at: '2026-11-16' },
    ...over,
  }
}

const DOC: ClassesDoc = {
  format: 'classes-1',
  generated_at: '2026-11-18T00:00:00Z',
  snapshot_id: 'snap',
  classes: [
    entry({
      id: 'inferencex',
      label: 'InferenceX, regular recipes',
      counts: { points: 20000, scored: 199, refused: 19801, failed: 0, withheld: 0 },
      grades: { G1: 0, G2: 0, G3: 0, G4: 199, G5: 19801 },
      accuracy_by_grade: { G1: none, G2: none, G3: none, G4: { ttft: fig(199, 25.7), tpot: fig(199, 24.0) } },
      engines: [{ engine: 'sglang', points: 100, graded: 0, grades: { G5: 100 } }],
    }),
    entry({
      id: 'inferencex-reconstructed',
      label: 'InferenceX, reconstructed recipe, G4',
      kind: 'reconstructed',
      interim: true,
      counts: { points: 213, scored: 213, refused: 0, failed: 0, withheld: 0 },
      grades: { G1: 0, G2: 0, G3: 0, G4: 213, G5: 0 },
      accuracy_by_grade: { G1: none, G2: none, G3: none, G4: { ttft: fig(213, 22.3, -3.2), tpot: fig(213, 15.1, 1.5) } },
      refusals: [],
      substitutions: [{ kind: 'client_difference', subject: 'send_gap', detail: 'closed loop', points: 213 }],
    }),
    entry({
      id: 'configiq',
      label: 'Red Hat configiq',
      kind: 'provisional',
      counts: { points: 30, scored: 12, refused: 10, failed: 0, withheld: 8 },
      grades: { G1: 0, G2: 0, G3: 12, G4: 0, G5: 10 },
      accuracy_by_grade: {
        G1: none,
        G2: none,
        G3: { ttft: fig(12, 186.5, 101), tpot: fig(12, 21.8, 1), itl: fig(12, 20.7, -14.1) },
        G4: { ttft: fig(0, 'too few points'), tpot: fig(0, 'too few points'), itl: fig(0, 'too few points') },
      },
    }),
  ],
}

function render(el: React.ReactElement): { html: string; errors: string[] } {
  const errors: string[] = []
  const spy = vi.spyOn(console, 'error').mockImplementation((...a) => {
    errors.push(a.map(String).join(' '))
  })
  const html = renderToStaticMarkup(el)
  spy.mockRestore()
  return { html, errors }
}
const card = (html: string, id: string) => html.match(new RegExp(`<section class="classcard[^"]*" id="class-${id}"[\\s\\S]*?</section>`))![0]
const text = (h: string) => h.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ')

describe('the classes page', () => {
  it('renders every class as its own card, with no console error and no NaN or undefined', () => {
    const { html, errors } = render(<Classes doc={DOC} error={null} />)
    expect(errors).toEqual([])
    expect(html).not.toMatch(/NaN|undefined|>null</)
    expect([...html.matchAll(/<section class="classcard/g)]).toHaveLength(3)
  })

  it("keeps each class's own counts, never a sum", () => {
    const { html } = render(<Classes doc={DOC} error={null} />)
    const reg = text(card(html, 'inferencex'))
    const rec = text(card(html, 'inferencex-reconstructed'))
    expect(reg).toContain('199 scored of 20,000 points')
    expect(rec).toContain('213 scored of 213 points')
    expect(html).not.toContain('20,213') // 20,000 + 213: the page adds nothing across classes
  })

  it('tags the reconstructed and provisional classes, and marks an interim one', () => {
    const { html } = render(<Classes doc={DOC} error={null} />)
    expect(text(card(html, 'inferencex-reconstructed'))).toMatch(/reconstructed recipe, G4.*interim/)
    expect(text(card(html, 'configiq'))).toContain('provisional, capped at G3, outside the headline')
    expect(text(card(html, 'inferencex'))).not.toMatch(/reconstructed|provisional|interim/)
  })

  it('shows accuracy by grade with ITL only where the class has it, and "too few points" under the minimum', () => {
    const { html } = render(<Classes doc={DOC} error={null} />)
    const cq = text(card(html, 'configiq'))
    expect(cq).toContain('ITL error')
    expect(cq).toContain('186.5% · median +101.0% · 12 pts')
    expect(text(card(html, 'inferencex'))).not.toContain('ITL error')
    expect(text(card(html, 'inferencex'))).toContain('25.7% · 199 pts')
    expect(cq).toContain('too few points')
  })

  it('names the reconstructed class\'s substitutions and each class\'s refusals', () => {
    const { html } = render(<Classes doc={DOC} error={null} />)
    expect(text(card(html, 'inferencex-reconstructed'))).toContain('client_difference send_gap 213 closed loop')
    expect(text(card(html, 'configiq'))).toContain('field_not_modelled moe_runner_backend 6')
  })

  it('says so when the classes could not be loaded, and while loading', () => {
    expect(render(<Classes doc={null} error="classes.json answered 404" />).html).toContain('classes.json answered 404')
    expect(render(<Classes doc={null} error={null} />).html).toContain('Loading the classes')
  })
})

describe('the classes tab', () => {
  it('is reached by the route, shown without the summary, and does not change the other views', () => {
    expect(parseRoute('#/?view=classes').view).toBe('classes')
    expect(routeToHash({ ...parseRoute('#/'), view: 'classes' })).toBe('#/?view=classes')
    expect(parseRoute('#/?view=dev').view).toBe('dev')
    expect(parseRoute('#/').view).toBe('overview')
    const { html, errors } = render(<App summary={null} loadError={null} initialHash="#/?view=classes" classes={DOC} />)
    expect(errors).toEqual([])
    expect(html).toContain('Classes of points')
    expect(html).toMatch(/class="tab on"[^>]*>\s*Classes/)
  })
})

describe('the committed classes.json', () => {
  const raw = JSON.parse(readFileSync(fileURLToPath(new URL('../../data/latest/classes.json', import.meta.url)), 'utf8'))
  it('validates and renders, regular class first', () => {
    const doc = validateClasses(raw)
    expect(doc.classes[0]!.id).toBe('inferencex')
    const { html, errors } = render(<Classes doc={doc} error={null} />)
    expect(errors).toEqual([])
    expect(html).not.toMatch(/NaN|undefined/)
  })
  it('is refused loudly when it is not a classes document', () => {
    expect(() => validateClasses({ format: 'classes-9', classes: [] })).toThrow(ClassesLoadError)
    expect(() => validateClasses({ format: 'classes-1', classes: [{ id: 'a', kind: 'mystery' }] })).toThrow(/lacks/)
  })
})
