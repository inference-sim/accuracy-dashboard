/**
 * v3 snapshots (design §11.3, COV-11): the headline over every graded point, G1 to G4, with each
 * grade's share, count and accuracy, "too few points" for a figure under the minimum, and the
 * points marked by grade. The fixtures are built by orchestrator/build_summary_v2.py from the
 * contract fixture (run-a; run-b with one point that timed out). v1 and v2 keep their own tests.
 */
import { describe, expect, it, vi } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { App } from './App'
import { validateSummary } from './load'
import { aggregatePair, flattenPoints } from './aggregate'
import { formatFigure } from './format'
import { sortModelKeys } from './sort'
import { buildRows } from './tree'
import { ProvenanceBody } from './components/Provenance'
import { Headline } from './components/Headline'
import { isEstimated, type Summary } from './types'

const load = (name: string): Summary =>
  validateSummary(JSON.parse(readFileSync(fileURLToPath(new URL(`../testdata/${name}`, import.meta.url)), 'utf8')))
const v3a = () => load('render-fixture.v3.summary.json')
const v3b = () => load('render-fixture.v3b.summary.json')

function render(el: React.ReactElement): { html: string; errors: string[] } {
  const errors: string[] = []
  const spy = vi.spyOn(console, 'error').mockImplementation((...a) => {
    errors.push(a.map(String).join(' '))
  })
  const html = renderToStaticMarkup(el)
  spy.mockRestore()
  return { html, errors }
}

const headline = (h: string) => h.match(/<section class="headline"[\s\S]*?<\/section>/)![0]

describe('a v3 snapshot renders', () => {
  it('with zero console errors and no NaN, undefined or null', () => {
    const { html, errors } = render(<App summary={v3a()} loadError={null} initialHash="#/?tier=all" />)
    expect(errors.join('\n')).toBe('')
    for (const bad of ['NaN', 'undefined', '>null<']) expect(html).not.toContain(bad)
  })

  it('heads the page with the accuracy over G1 to G4, and says "too few points" under the minimum', () => {
    const h = headline(render(<App summary={v3a()} loadError={null} initialHash="#/" />).html)
    expect(h).toContain('G1 to G4')
    // run-a holds 9 graded points, under the minimum of 10: no figure is shown as a number.
    expect(h).toContain('too few points')
    expect(h).not.toMatch(/\d+\.\d%<\/div><div class="stat-label">Mean time/)
    expect(h).toContain('9 graded of 14 measurements, 5 not scored')
  })

  it('shows every graded grade with its count, share and accuracy', () => {
    const h = headline(render(<App summary={v3a()} loadError={null} initialHash="#/" />).html)
    for (const g of ['G1', 'G2', 'G3', 'G4']) expect(h).toContain(`<th scope="row">${g} `)
    // Under the minimum a grade shows its count and no share (COV-11): G1, G2 and G4 hold 3 points, G3 none.
    expect(h).toContain('<td>3</td><td>too few points</td>')
    expect(h).toContain('<td>0</td><td>too few points</td>')
    expect(h).not.toContain('33.3%')
  })

  it('shows a figure over enough points as a number with its count', () => {
    const s = v3a()
    const h = s.headline!
    const big = { ...h, headline: { ttft: { mape: 12.34, n: 40 }, tpot: { mape: 5.5, n: 40 } } }
    const html = renderToStaticMarkup(
      <Headline totals={s.totals} tier="all" points={9} models={3} blisRelease="v0.12.0" dataDate={null} graded={big} />,
    )
    expect(html).toContain('12.3%')
    expect(html).toContain('40 points')
  })

  it('names the grade and each substitution in a point\'s tooltip', () => {
    const pts = flattenPoints(v3a())
    // The scorer grades no point G1 until the four conditions it does not check are graded
    // (grade.UNCHECKED_KINDS), so the fixture holds none; a G1 record is a G2 one with nothing named.
    expect(pts.some((p) => p.fidelity?.grade === 'G1')).toBe(false)
    const g2 = pts.find((p) => p.fidelity?.grade === 'G2')!
    const g1 = { fidelity: { ...g2.fidelity!, grade: 'G1' as const, substitutions: [] } }
    const g4 = pts.find((p) => p.fidelity?.grade === 'G4' && p.fidelity.run_release === '0.25.0')!
    expect(renderToStaticMarkup(<ProvenanceBody fidelity={g1.fidelity!} />)).toContain('G1 · Exact match')
    const four = renderToStaticMarkup(<ProvenanceBody fidelity={g4.fidelity!} />)
    expect(four).toContain('G4')
    expect(four).toContain('measured on vLLM 0.25.0')
  })

  it('puts only G1 points in the exact tier', () => {
    const pts = flattenPoints(v3a())
    for (const p of pts) {
      expect(isEstimated(p.fidelity)).toBe(p.fidelity!.grade !== 'G1')
      expect(p.tier).toBe(p.fidelity!.grade === 'G1' ? 'measured_or_resolved' : 'all')
    }
    expect(isEstimated({ ...pts[0]!.fidelity!, grade: 'G1', substitutions: [] })).toBe(false)
  })

  it('counts graded points over every point, and a failed one apart', () => {
    const a = render(<App summary={v3a()} loadError={null} initialHash="#/" />).html
    expect(a).toMatch(/points graded<\/span><\/span> <b>9<\/b> of 14|points graded.*?<b>9<\/b> of 14/)
    const b = render(<App summary={v3b()} loadError={null} initialHash="#/" />).html
    expect(b).toMatch(/failed <b>1<\/b>/)
  })
})


describe('a v3 node over fewer than the minimum points (COV-11)', () => {
  it('shows "too few points" in the table at every level, never a number', () => {
    const s = v3a()
    const html = render(<App summary={s} loadError={null} initialHash="#/?tier=all" />).html
    const table = html.slice(html.indexOf('<table class="readout"'), html.indexOf('</table>', html.indexOf('<table class="readout"')))
    expect(table).toContain('<span class="num">too few points</span>')
    expect(table).not.toMatch(/<span class="num">\d/)
  })

  it('aggregates a count under the minimum as too few points, and sorts it as missing', () => {
    const pts = flattenPoints(v3a()).slice(0, 3)
    const under = aggregatePair(pts, 10)
    expect(under.all.mape.ttft).toBe('too few points')
    expect(under.all.mape.n).toBe(3)
    expect(aggregatePair(pts).all.mape.ttft).toEqual(expect.any(Number))
    const rows = buildRows(pts, new Set(), 10)
    expect(sortModelKeys(rows, { key: 'ttft_mape', dir: 1 }, 'all')).toEqual(rows.map((r) => r.label))
    const num = { ...rows[0]!, label: 'zz', metrics: aggregatePair(pts, 0) }
    expect(sortModelKeys([rows[0]!, num], { key: 'ttft_mape', dir: 1 }, 'all')).toEqual(['zz', rows[0]!.label])
  })

  it('formats such a figure as the text, not a percent', () => {
    expect(formatFigure('too few points')).toBe('too few points')
    expect(formatFigure(12.34)).toBe('12.3%')
    expect(formatFigure(null)).toBe('—')
  })
})
