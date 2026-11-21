/**
 * The sources page (data/latest/funnel.json, funnel.py): each anchor source is its own card with its scored count and the reason
 * of every unscored unit, InferenceX shows its vLLM and SGLang lanes apart, a training-only source is a labelled training
 * diagnostic with no scored count, and a ledger.yaml that disagrees with D9 is stated. The fixture is written by
 * orchestrator/baseline/test_funnel.py (test_the_web_fixture_is_what_funnel_py_writes), so producer and consumer cannot drift.
 */
import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { App } from './App'
import { Sources } from './components/Sources'
import { FunnelLoadError, fetchFunnel, shouldFetchFunnel, unscoredReasons, validateFunnel, type FunnelDoc } from './sources'
import { parseRoute, routeToHash } from './route'

const raw = JSON.parse(readFileSync(fileURLToPath(new URL('../testdata/funnel-2.fixture.json', import.meta.url)), 'utf8'))
const DOC = validateFunnel(raw)
const clone = () => JSON.parse(JSON.stringify(raw))
const html = (doc: FunnelDoc | null, error: string | null = null) => renderToStaticMarkup(<Sources doc={doc} error={error} />)

describe('the Sources page', () => {
  it('gives each anchor source its own card, scored count and unscored reasons', () => {
    const h = html(DOC)
    expect(h).toContain('id="source-inferencex"')
    expect(h).toContain('id="source-configiq"')
    expect(h).toContain('of 6 in-scope anchor units')
    expect(h).toContain('field_unclassified')
    expect(h).toContain('engine_unsupported')
    expect(h).toContain('value_not_recorded')
    expect(h).toContain('Anchor rule: every unit (plan: anchor-only), less the units the D2 join found read under a training role')
  })

  it('shows the InferenceX vLLM and SGLang lanes apart, each with its own reasons', () => {
    const h = html(DOC)
    for (const lane of ['vllm', 'sglang', 'other']) expect(h).toContain(`id="source-inferencex-lane-${lane}"`)
    const sg = h.slice(h.indexOf('source-inferencex-lane-sglang'), h.indexOf('source-inferencex-lane-vllm') > h.indexOf('source-inferencex-lane-sglang') ? h.indexOf('source-inferencex-lane-vllm') : undefined)
    expect(sg).toContain('field_unclassified')
    expect(sg).not.toContain('row_differs')
  })

  it('shows a training-only source as a labelled training diagnostic with no scored count or accuracy', () => {
    const h = html(DOC)
    const t = h.slice(h.indexOf('id="training-vllm-ci-perf"'))
    expect(t).toContain('training only')
    expect(t).toContain('No accuracy is reported for this source')
    expect(t).not.toContain('stat-label">scored')
    expect(h).not.toMatch(/id="source-vllm-ci-perf"/)
  })

  it('states where ledger.yaml disagrees with D9, and says when it was not checked', () => {
    expect(html(DOC)).toContain('ledger.yaml disagrees with design D9')
    const unchecked = clone()
    unchecked.cut_points = { checked: false, discrepancies: [] }
    const h = html(validateFunnel(unchecked))
    expect(h).toContain('was not checked against design D9')
    expect(h).not.toContain('disagrees with design D9')
    const agrees = clone()
    agrees.cut_points = { checked: true, discrepancies: [] }
    const a = html(validateFunnel(agrees))
    expect(a).not.toContain('disagrees with design D9')
    expect(a).not.toContain('was not checked')
  })

  it('says it is loading, and shows a load error as it is', () => {
    expect(html(null)).toContain('Loading the per-source funnels')
    expect(html(null, 'funnel.json answered 404')).toContain('funnel.json answered 404')
  })

  it('is a tab of the app, opened by view=sources and linkable', () => {
    const r = parseRoute('#/?view=sources')
    expect(r.view).toBe('sources')
    expect(routeToHash(r)).toBe('#/?view=sources')
    const h = renderToStaticMarkup(<App summary={null} loadError={null} initialHash="#/?view=sources" funnel={DOC} />)
    expect(h).toContain('id="source-inferencex"')
    expect(h).toContain('>Sources<')
  })
})

describe('the funnel data', () => {
  it('lists the reasons of the unscored units largest first', () => {
    const f = DOC.funnels.inferencex!
    const r = unscoredReasons(f)
    expect(r.map((x) => x.units)).toEqual([...r.map((x) => x.units)].sort((a, b) => b - a))
    expect(r.reduce((n, x) => n + x.units, 0)).toBe(f.stages.in_scope - f.stages.scored - f.provisional.units)
  })

  it('refuses a wrong format, a missing part, a training source given a scored count, and a missing cut-point check', () => {
    const bad = (mut: (d: any) => void, msg: RegExp) => {
      const d = clone()
      mut(d)
      expect(() => validateFunnel(d)).toThrow(msg)
    }
    bad((d) => (d.format = 'funnel-1'), /renders funnel-2/)
    bad((d) => (d.funnels = {}), /no funnels/)
    bad((d) => delete d.funnels.inferencex.g5, /lacks "g5"/)
    bad((d) => (d.training['vllm-ci-perf'].stages.scored = 3), /no scored count or accuracy/)
    bad((d) => (d.training['vllm-ci-perf'].accuracy = { mape: 3 }), /no scored count or accuracy/)
    bad((d) => (d.training['vllm-ci-perf'].role = 'anchor'), /training-only/)
    bad((d) => delete d.cut_points, /lacks cut_points/)
    expect(() => validateFunnel(null)).toThrow(FunnelLoadError)
  })

  it('fetches only when the Sources tab is open and nothing is held, and reports a non-OK answer', async () => {
    expect(shouldFetchFunnel('sources', null, null, true)).toBe(true)
    expect(shouldFetchFunnel('classes', null, null, true)).toBe(false)
    expect(shouldFetchFunnel('sources', DOC, null, true)).toBe(false)
    expect(shouldFetchFunnel('sources', null, 'x', true)).toBe(false)
    expect(shouldFetchFunnel('sources', null, null, false)).toBe(false)
    await expect(fetchFunnel((async () => ({ ok: false, status: 404 })) as unknown as typeof fetch)).rejects.toThrow(/404/)
    await expect(fetchFunnel((async () => ({ ok: true, json: async () => raw })) as unknown as typeof fetch)).resolves.toMatchObject({ format: 'funnel-2' })
  })
})
