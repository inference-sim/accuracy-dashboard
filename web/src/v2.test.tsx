/**
 * v2 snapshots (#30, Discussion #28): per-point provenance, the measurement date, not-scored
 * points kept out of the DOM, and Compare across v2 runs. The fixtures are built by
 * orchestrator/build_summary_v2.py from the contract fixture (run-a, and run-b scored by an older
 * BLIS with one point refused). v1 behaviour is covered, unchanged, by the other test files.
 */
import { describe, expect, it, vi } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { App } from './App'
import { validateSummary } from './load'
import { flattenPoints, intersectByKey, pointKey } from './aggregate'
import { ProvenanceBody } from './components/Provenance'
import type { Summary } from './types'

const load = (name: string): Summary =>
  validateSummary(JSON.parse(readFileSync(fileURLToPath(new URL(`../testdata/${name}`, import.meta.url)), 'utf8')))
const v2a = () => load('render-fixture.v2.summary.json')
const v2b = () => load('render-fixture.v2b.summary.json')
const v1 = () => load('render-fixture.summary.json')

function render(el: React.ReactElement): { html: string; errors: string[] } {
  const errors: string[] = []
  const spy = vi.spyOn(console, 'error').mockImplementation((...a) => {
    errors.push(a.map(String).join(' '))
  })
  const html = renderToStaticMarkup(el)
  spy.mockRestore()
  return { html, errors }
}

function clean(html: string) {
  expect(html).not.toContain('NaN')
  expect(html).not.toContain('undefined')
  expect(html).not.toContain('>null<')
}

describe('a v2 snapshot renders', () => {
  it('with zero console errors and no NaN / blank cells', () => {
    const { html, errors } = render(<App summary={v2a()} loadError={null} initialHash="#/?tier=all" />)
    expect(errors.join('\n')).toBe('')
    clean(html)
    expect(html).toContain('deepseek-v4.1-flash')
  })

  it('shows the measured date column and a provenance mark per point', () => {
    const s = v2a()
    const p = flattenPoints(s).find((x) => x.gpu === 'h200' && x.topoLabel.includes('tp4'))!
    const { html, errors } = render(
      <App summary={s} loadError={null} initialHash={`#/?sel=${encodeURIComponent(p.sweepKey)}&tier=all`} />,
    )
    expect(errors.join('\n')).toBe('')
    expect(html).toContain('>Measured<')
    expect(html).toContain('2026-09-21')
    // one ✓ per exact point in that sweep (3 concurrencies), each focusable with an accessible label
    expect(html.match(/aria-label="exact match"/g)?.length).toBe(3)
    clean(html)
  })

  it('marks an approximate point ≈, and an exact one ⓘ', () => {
    const s = v2a()
    const approx = flattenPoints(s).find((x) => x.fidelity?.status === 'approximate')!
    const { html } = render(
      <App summary={s} loadError={null} initialHash={`#/?sel=${encodeURIComponent(approx.sweepKey)}&tier=all`} />,
    )
    expect(html).toContain('prov-mark approx')
    expect(html).toContain('≈')
  })

  it('keeps not-scored points out of the DOM and counts their reasons', () => {
    const s = v2a()
    expect(s.not_scored!.length).toBe(4)
    const { html } = render(<App summary={s} loadError={null} initialHash="#/?tier=all" />)
    for (const ns of s.not_scored!) expect(html).not.toContain(ns.point_id)
    // the minimax-m3 rows are all not scored (EAGLE3): no minimax row is drawn
    expect(html).not.toContain('minimaxm3')
    expect(html).toContain('drafter not in catalog 2')
  })

  it('leaves the v1 fixture without a date column or provenance marks', () => {
    const s = v1()
    const p = flattenPoints(s)[0]!
    const { html } = render(
      <App summary={s} loadError={null} initialHash={`#/?sel=${encodeURIComponent(p.sweepKey)}&tier=all`} />,
    )
    expect(html).not.toContain('>Measured<')
    expect(html).not.toContain('prov-mark')
  })
})

describe('the tier follows the match record', () => {
  it('reads exact / all (including estimations) on a v2 snapshot, and keeps the v1 wording on v1', () => {
    const { html } = render(<App summary={v2a()} loadError={null} initialHash="#/" />)
    expect(html).toContain('>exact<')
    expect(html).toContain('>all (including estimations)<')
    expect(html).not.toContain('measured·resolved')
    const old = render(<App summary={v1()} loadError={null} initialHash="#/" />).html
    expect(old).toContain('measured·resolved')
  })

  it('an estimated point is in all only; every exact point is in the exact tier', () => {
    for (const p of flattenPoints(v2a()))
      expect(p.tier).toBe(p.fidelity!.status === 'approximate' ? 'all' : 'measured_or_resolved')
  })
})

describe('dates are labelled for what they are', () => {
  it('the headline gives the data range and the API pull date, never a "data from <pull date>"', () => {
    const { html } = render(<App summary={v2a()} loadError={null} initialHash="#/?tier=all" />)
    expect(html).toContain('InferenceX data range 2026-09-03 to 2026-10-03')
    expect(html).toContain('API pull date 2026-10-23')
    expect(html).not.toContain('InferenceX data from')
  })

  it('the run details say API pull date / data range, not dump / through', () => {
    const { html } = render(<App summary={v2a()} loadError={null} initialHash="#/?tier=all" />)
    expect(html).toContain('>API pull date<')
    expect(html).toContain('2026-10-23 00:00 UTC')
    expect(html).toContain('>data range<')
    expect(html).not.toContain('>dump<')
    expect(html).not.toContain('>through<')
  })

  it('drops the v1-only hidden/failed buckets and the duplicate generated time', () => {
    const { html } = render(<App summary={v2a()} loadError={null} initialHash="#/?tier=all" />)
    expect(html).not.toContain('(hidden)')
    expect(html).not.toContain('>generated<')
    expect(html).toContain('>latest run date<')
    expect(html).not.toContain('>snapshot<')
  })

  it('a v1 snapshot keeps its dump wording', () => {
    const { html } = render(<App summary={v1()} loadError={null} initialHash="#/?tier=all" />)
    expect(html).toContain('InferenceX data from 2026-09-28')
    expect(html).toContain('>dump<')
  })
})

describe('the match tooltip shows only what differs, in plain words', () => {
  const body = (status: 'exact' | 'approximate') => {
    // exact: DeepSeek-V4.1-Flash h200 TP8 c1 (its max_num_seqs is BLIS's default); approximate: b200 DEP2
    const p = flattenPoints(v2a()).find((x) =>
      status === 'approximate' ? x.fidelity?.status === 'approximate' : x.gpu === 'h200' && x.topoLabel.includes('tp8'))!
    return renderToStaticMarkup(<ProvenanceBody fidelity={p.fidelity!} measuredDate={p.measuredDate} />)
  }

  it('an exact point says so in one line, plus any default BLIS filled in and the build distance', () => {
    const html = body('exact')
    expect(html).toContain('Exact match')
    expect(html).toContain('BLIS simulated the exact settings this run used.')
    expect(html).toContain('Max concurrent requests</b>: not recorded by the run, so BLIS used its default (1024)')
    expect(html).toContain('738 commits older than v0.31.0, the release BLIS models')
  })

  it('an approximate point names each difference with both sides, and the issue once', () => {
    const html = body('approximate')
    expect(html).toContain('Estimated')
    expect(html).toContain('Indexer cache format</b>: run used mxfp4, BLIS used fp8')
    expect(html).toContain('Sparse indexer</b>: run used on, BLIS used off')
    expect(html.match(/inference-sim\/blis-schemas#57/g)?.length).toBe(1)
    expect(html).toContain('Counted only in “all (including estimations)”')
  })

  it('leaves out everything that matched and all internal names', () => {
    const html = body('approximate')
    for (const gone of ['moe_backend', 'engine.', 'router', 'kv cache tokens', 'from server args', 'attention_config', 'ResolveVLLMBatchDefaults'])
      expect(html).not.toContain(gone)
    expect(html.length).toBeLessThan(900)
  })
})

describe('Compare across v2 runs', () => {
  it('keys points by date as well, so re-measurements stay distinct', () => {
    const p = flattenPoints(v2a())[0]!
    expect(pointKey(p).endsWith(`|${p.measuredDate}`)).toBe(true)
    const q = flattenPoints(v1())[0]!
    expect(pointKey(q).split('|').length).toBe(6)
  })

  it('intersects run-a and run-b: 7 shared, the refused point left out', () => {
    const { pairs, onlyA, onlyB } = intersectByKey(flattenPoints(v2a()), flattenPoints(v2b()))
    expect(pairs.length).toBe(7)
    expect(onlyA + onlyB).toBe(1)
  })

  it('renders the Δ view and says N of M points', () => {
    const a = v2a()
    const b = v2b()
    const { html, errors } = render(
      <App summary={a} summaryB={b} loadError={null} initialHash={`#/?run=${a.snapshot_id}&runB=${b.snapshot_id}`} />,
    )
    expect(errors.join('\n')).toBe('')
    expect(html).toContain('Comparing 7 of 8 points')
    clean(html)
  })

  it('refuses to diff a v1 run against a v2 run', () => {
    const a = v2a()
    const b = v1()
    const { html, errors } = render(
      <App summary={a} summaryB={b} loadError={null} initialHash={`#/?run=${a.snapshot_id}&runB=${b.snapshot_id}`} />,
    )
    expect(errors.join('\n')).toBe('')
    expect(html).toContain('different ingests')
    expect(html).not.toContain('Comparing')
  })
})
