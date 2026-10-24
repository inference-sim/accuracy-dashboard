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
import { aggregatePair, flattenPoints, intersectByKey, pointKey } from './aggregate'
import { tierV2Definition } from './glossary'
import { ProvenanceBody, VersionBody, VersionTip } from './components/Provenance'
import { buildRows } from './tree'
import { PointsTable } from './components/PointsTable'
import { Compare } from './components/Compare'
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
    expect(html).toContain('>InferenceX run date<')
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

  it('keeps not-scored points out of the DOM and reports only how many', () => {
    const s = v2a()
    expect(s.not_scored!.length).toBe(4)
    const { html } = render(<App summary={s} loadError={null} initialHash="#/?tier=all" />)
    for (const ns of s.not_scored!) expect(html).not.toContain(ns.point_id)
    // the minimax-m3 rows are all not scored (EAGLE3): no minimax row is drawn
    expect(html).not.toContain('minimaxm3')
    expect(html).toMatch(/not scored <b>4<\/b>/)
    for (const reason of ['drafter not in catalog', 'setting not modelled', 'model not in catalog']) expect(html).not.toContain(reason)
  })

  it('leaves the v1 fixture without a date column or provenance marks', () => {
    const s = v1()
    const p = flattenPoints(s)[0]!
    const { html } = render(
      <App summary={s} loadError={null} initialHash={`#/?sel=${encodeURIComponent(p.sweepKey)}&tier=all`} />,
    )
    expect(html).not.toContain('>InferenceX run date<')
    expect(html).not.toContain('prov-mark')
  })
})

describe('the tier follows the match record', () => {
  it('reads exact / estimated / all on a v2 snapshot, and keeps the v1 wording on v1', () => {
    const { html } = render(<App summary={v2a()} loadError={null} initialHash="#/" />)
    expect(html).toContain('>exact<')
    expect(html).toContain('>estimated<')
    expect(html).toContain('>all<')
    expect(html).not.toContain('including estimations')
    expect(html).not.toContain('measured·resolved')
    const old = render(<App summary={v1()} loadError={null} initialHash="#/" />).html
    expect(old).toContain('measured·resolved')
    expect(old).not.toContain('>estimated<')
  })

  it('the estimated tier lists only deployments with estimated points, and the headline is unchanged', () => {
    const s = v2a()
    const exact = render(<App summary={s} loadError={null} initialHash="#/" />).html
    const est = render(<App summary={s} loadError={null} initialHash="#/?tier=estimated" />).html
    const headline = (h: string) => h.match(/<section class="headline"[\s\S]*?<\/section>/)![0]
    expect(headline(est)).toBe(headline(exact))
    // the only estimated point is DeepSeek-V4.1-Flash; DeepSeek-V4-Pro (all exact) drops out
    expect(est).toContain('deepseek-v4.1-flash')
    expect(est).not.toContain('deepseek-v4-pro')
    expect(exact).toContain('deepseek-v4-pro')
  })

  it('an estimated point is in all only; every exact point is in the exact tier', () => {
    for (const p of flattenPoints(v2a()))
      expect(p.tier).toBe(p.fidelity!.status === 'approximate' ? 'all' : 'measured_or_resolved')
  })
})

describe('the tier controls what the table lists', () => {
  it('the exact tier lists no estimated-only deployment (no rows of dashes)', () => {
    const s = v2a()
    // expand everything: model, workload and every GPU
    const pts = flattenPoints(s)
    const ids = new Set<string>()
    for (const p of pts) {
      ids.add(`m:${p.model}`)
      ids.add(`m:${p.model}|w:${p.workloadLabel}`)
      ids.add(`m:${p.model}|w:${p.workloadLabel}|g:${p.gpu}`)
    }
    const estimatedOnly = [...new Set(pts.map((p) => p.sweepKey))].filter((k) =>
      pts.filter((p) => p.sweepKey === k).every((p) => p.fidelity!.status === 'approximate'))
    expect(estimatedOnly.length).toBeGreaterThan(0)
    const exact = buildRows(pts.filter((p) => p.tier === 'measured_or_resolved'), ids)
    for (const k of estimatedOnly) expect(exact.some((r) => r.sweepKey === k)).toBe(false)
    const all = buildRows(pts, ids)
    for (const k of estimatedOnly) expect(all.some((r) => r.sweepKey === k)).toBe(true)
  })
})

describe('dates are labelled for what they are', () => {
  it('the headline gives the data range and the API pull date, never a "data from <pull date>"', () => {
    const { html } = render(<App summary={v2a()} loadError={null} initialHash="#/?tier=all" />)
    expect(html).toContain('InferenceX data range 2026-09-03 to 2026-10-11')
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

  it('says "1 model", not "1 models"', () => {
    const { html } = render(<App summary={v2a()} loadError={null} initialHash="#/?tier=all" />)
    expect(html).not.toContain('1 models')
    expect(html).toMatch(/\b\d+ measurements \(\d+ exact, \d+ estimated\) · 3 models/)
    const one = v2a()
    one.matrix = one.matrix.slice(0, 1)
    expect(render(<App summary={one} loadError={null} initialHash="#/?tier=all" />).html).toContain(' · 1 model · ')
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
    return renderToStaticMarkup(<ProvenanceBody fidelity={p.fidelity!} />)
  }

  it('an exact point says so in one line, and nothing about settings vLLM and BLIS both defaulted', () => {
    // h200 TP8 c1 didn't pass max_num_seqs: vLLM ran its default and BLIS the same one.
    const html = body('exact')
    expect(html).toContain('Exact match')
    expect(html).toContain('BLIS simulated the exact settings this run used.')
    expect(html).not.toContain('Max concurrent requests')
    expect(html).not.toContain('default')
    expect(html).not.toContain('commits')            // the build distance is on the vLLM version
  })

  it('an approximate point names each difference with both sides, and nothing else', () => {
    const html = body('approximate')
    expect(html).toContain('Estimated')
    // a small table: setting | this run | BLIS, one row per estimated setting
    expect(html).toContain('role="table"')
    expect(html.match(/role="row"/g)?.length).toBe(1 + 2)   // header + the fixture's 2 estimated settings
    expect(html).toMatch(/Indexer cache format<\/span><span role="cell" class="mono">mxfp4<\/span><span role="cell">fp8/)
    expect(html).toMatch(/Sparse indexer<\/span><span role="cell" class="mono">on<\/span><span role="cell">off/)
    for (const gone of ['#57', 'blis-schemas', 'can’t represent', 'commits'])
      expect(html).not.toContain(gone)
  })

  it('leaves out everything that matched and all internal names', () => {
    const html = body('approximate')
    expect(html).not.toContain('measured')
    for (const gone of ['moe_backend', 'engine.', 'router', 'kv cache tokens', 'from server args', 'attention_config', 'ResolveVLLMBatchDefaults'])
      expect(html).not.toContain(gone)
    expect(html.replace(/<[^>]+>/g, '').length).toBeLessThan(400)   // what a reader actually reads
  })
})

describe('an estimated weight format reads plainly', () => {
  it('names the setting and both formats', () => {
    const f = flattenPoints(v2a()).find((x) => x.fidelity?.status === 'approximate')!.fidelity!
    const q = { ...f, args: [{ arg: 'quantization', measured: 'modelopt_mixed', blis: 'modelopt_fp4', match: 'approximated' as const, source: 'resolved_config' as const, note: 'n' }] }
    const html = renderToStaticMarkup(<ProvenanceBody fidelity={q} />)
    expect(html).toMatch(/Weight format<\/span><span role="cell" class="mono">nvfp4 \+ mxfp8 \(mixed\)<\/span><span role="cell">nvfp4/)
  })
})

describe('a deployment row with some estimated points', () => {
  it('shows an estimated record, never "Exact match" under a count of estimated points', () => {
    const a = v2a()
    const f = flattenPoints(a)
    const exactP = f.find((p) => p.fidelity?.status === 'exact')!
    const est = f.find((p) => p.fidelity?.status === 'approximate')!
    // put an estimated point after an exact one inside the same deployment row
    const mixed = [exactP, { ...est, sweepKey: exactP.sweepKey, model: exactP.model, workloadLabel: exactP.workloadLabel,
                             gpu: exactP.gpu, topoLabel: exactP.topoLabel, pointId: 'e'.repeat(64) }]
    // expand every level down to the deployment row
    const ids = new Set<string>()
    for (let i = 0; i < 4; i++) for (const r of buildRows(mixed, ids)) ids.add(r.id)
    const row = buildRows(mixed, ids).find((r) => r.level === 'topology')!
    expect(row.approxCount).toBe(1)
    expect(row.fidelity!.status).toBe('approximate')
  })
})

describe('estimated kernel settings read plainly', () => {
  it('names the MoE kernel each side ran, and the fusion pass', () => {
    const f = flattenPoints(v2a()).find((x) => x.fidelity?.status === 'approximate')!.fidelity!
    const q = { ...f, args: [
      { arg: 'env.VLLM_MXFP4_USE_MARLIN', measured: true, blis: false, match: 'approximated' as const, source: 'engine_line' as const, note: 'n' },
      { arg: 'compilation_config.pass_config.fuse_minimax_qk_norm', measured: true, blis: false, match: 'approximated' as const, source: 'args' as const, note: 'n' },
    ] }
    const html = renderToStaticMarkup(<ProvenanceBody fidelity={q} />)
    expect(html).toMatch(/MoE kernel<\/span><span role="cell" class="mono">Marlin<\/span><span role="cell">default kernel/)
    expect(html).toMatch(/QK-norm fusion<\/span><span role="cell" class="mono">on<\/span><span role="cell">off/)
    for (const internal of ['VLLM_', 'fuse_minimax', 'env.']) expect(html).not.toContain(internal)
  })
})

describe('the results download', () => {
  it('sits above "How this was measured", with a plain label', () => {
    const html = renderToStaticMarkup(<App summary={v2a()} loadError={null} />)
    const dl = html.indexOf('Download all results (JSON)')
    expect(dl).toBeGreaterThan(-1)
    expect(dl).toBeLessThan(html.indexOf('How this was measured'))
    expect(html).toContain('download="blis-accuracy-results.json"')
    expect(html).not.toContain('⤓ summary.json')
  })
})

describe('run details link InferenceX itself, not its API root', () => {
  it('source links the InferenceX site; the API pull date is plain text', () => {
    const html = renderToStaticMarkup(<App summary={v2a()} loadError={null} />)
    const about = html.slice(html.indexOf('class="about-prov"'))
    expect(about).toContain('href="https://inferencex.semianalysis.com/"')
    expect(about).toContain('>InferenceX</a>')
    expect(html).not.toContain('inferencex.semianalysis.com/api')
    expect(about).toMatch(/API pull date<\/span><span class="v">2026-10-23 00:00 UTC<\/span>/)
  })
})

describe('the default view is every point, and the tier text names the build window', () => {
  it('opens on all: the headline and the table cover every scored point', () => {
    const a = v2a()
    const html = renderToStaticMarkup(<App summary={a} loadError={null} />)
    expect(html).toContain('<span class="clk on">all</span>')
    const n = flattenPoints(a).length
    expect(html).toContain(`${n} measurements`)
    const all = aggregatePair(flattenPoints(a)).all.mape.ttft!
    const pct = (v: number) => `${v.toLocaleString('en-US', { minimumFractionDigits: 1, maximumFractionDigits: 1 })}%`
    expect(html.slice(html.indexOf('class="stats"'), html.indexOf('class="context"'))).toContain(pct(all))
  })

  it('the tier explanation reads the release and commit window from the snapshot', () => {
    const a = v2a()
    expect(tierV2Definition(a.provenance.vllm_ref!, a.provenance.vllm_max_distance!)).toContain(
      'within 2,000 commits of v0.31.0, the release BLIS is calibrated on')
    // Another snapshot's window is its own, not a number written into the UI.
    expect(tierV2Definition('v0.40.0', 500)).toContain('within 500 commits of v0.40.0')
    expect(tierV2Definition('v0.40.0', 500)).not.toMatch(/2,000|v0\.31/)
  })
})

describe('a build BLIS doesn’t model is scored as estimated', () => {
  const custom = () => flattenPoints(v2a()).find((x) => x.fidelity?.build.match === 'estimated')!

  it('is in the estimated and all tiers, not exact', () => {
    const p = custom()
    expect(p.fidelity!.status).toBe('approximate')
    expect(p.tier).toBe('all')
  })

  it('the match tooltip names the build as the only difference', () => {
    const html = renderToStaticMarkup(<ProvenanceBody fidelity={custom().fidelity!} />)
    expect(html).toContain('BLIS simulated the exact settings this run used, but not its vLLM build:')
    expect(html).toMatch(/vLLM build<\/span><span role="cell">a custom build<\/span><span role="cell">v0.31.0/)
    expect(html.match(/role="row"/g)?.length).toBe(2)   // header + the build
  })

  it('a build too far from the release says how far, in the table', () => {
    const f = custom().fidelity!
    const far = { ...f, build: { ...f.build, commit: 'a'.repeat(40), distance: -2500, why: 'outside_distance' as const } }
    const html = renderToStaticMarkup(<ProvenanceBody fidelity={far} />)
    expect(html).toContain('2,500 commits older than v0.31.0')
  })

  it('its version tooltip says it isn’t the release BLIS models', () => {
    const html = renderToStaticMarkup(<VersionBody build={custom().fidelity!.build} />)
    expect(html).toContain('This run’s vLLM build is a custom build; BLIS models v0.31.0.')
  })
})

describe('the vLLM version says how far its build is from the release BLIS models', () => {
  const tip = (gpu: string) => {
    const p = flattenPoints(v2a()).find((x) => x.gpu === gpu && x.engineVersion)!
    return renderToStaticMarkup(<VersionTip version={p.engineVersion!} fidelity={p.fidelity} />)
  }

  it('a v2 point: the badge is a tooltip trigger with the commit distance', () => {
    const html = tip('h200')
    expect(html).toContain('class="ver neutral"')
    expect(html).toContain('aria-label="vLLM build"')
    const p = flattenPoints(v2a()).find((x) => x.gpu === 'h200')!
    expect(renderToStaticMarkup(<VersionBody build={p.fidelity!.build} />)).toContain(
      'This run’s vLLM build is 738 commits older than v0.31.0, the release BLIS models.')
  })

  it('a v1 point (no build record) shows the plain badge', () => {
    const p = flattenPoints(v1()).find((x) => x.engineVersion)!
    const html = renderToStaticMarkup(<VersionTip version={p.engineVersion!} fidelity={p.fidelity} />)
    expect(html).toMatch(/^<span class="ver neutral">[^<]+<\/span>$/)
  })

  it('the points table uses it', () => {
    const a = v2a()
    const p = flattenPoints(a).find((x) => x.gpu === 'h200')!
    const html = renderToStaticMarkup(<App summary={a} loadError={null} initialHash={`#/?tier=all&sel=${encodeURIComponent(p.sweepKey)}`} />)
    expect(html.slice(html.indexOf('readout pts'))).toContain('aria-label="vLLM build"')
  })
})

describe('Compare across v2 runs', () => {
  it('keys v2 points by their contract id; a v1 point keeps its label key', () => {
    const pts = flattenPoints(v2a())
    const p = pts[0]!
    expect(pointKey(p)).toBe(p.pointId)
    expect(new Set(pts.map(pointKey)).size).toBe(pts.length)
    // two deployments with the same label (one copied with a drafter switched on) never share a
    // key, so Compare can't pair one with the other
    const twin = { ...p, pointId: 'f'.repeat(64) }
    expect(pointKey(twin)).not.toBe(pointKey(p))
    // an older v2 point without an id falls back to the label key with its date
    const { pointId: _drop, ...noId } = p
    expect(pointKey(noId).endsWith(`|${p.measuredDate}`)).toBe(true)
    const q = flattenPoints(v1())[0]!
    expect(pointKey(q).split('|').length).toBe(6)
  })

  it('intersects run-a and run-b: 8 shared, the refused point left out', () => {
    const { pairs, onlyA, onlyB } = intersectByKey(flattenPoints(v2a()), flattenPoints(v2b()))
    expect(pairs.length).toBe(8)
    expect(onlyA + onlyB).toBe(1)
  })

  it('renders the Δ view and says N of M points', () => {
    const a = v2a()
    const b = v2b()
    const { html, errors } = render(
      <App summary={a} summaryB={b} loadError={null} initialHash={`#/?run=${a.snapshot_id}&runB=${b.snapshot_id}`} />,
    )
    expect(errors.join('\n')).toBe('')
    expect(html).toContain('Comparing 8 of 9 points')
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

describe('the headline says how many of its points are estimated', () => {
  it('splits the count beside the all-tier headline', () => {
    const { html } = render(<App summary={v2a()} loadError={null} initialHash="#/" />)
    expect(html).toContain('9 measurements (7 exact, 2 estimated)')
  })

  it('a v1 snapshot shows the plain count', () => {
    const { html } = render(<App summary={v1()} loadError={null} initialHash="#/" />)
    expect(html).not.toMatch(/measurements \(\d+ exact/)
  })
})

describe('repeats at one concurrency are separate InferenceX sweeps', () => {
  const pts = () => {
    const all = flattenPoints(v2a())
    const t = all.find((p) => p.model === 'deepseek-v4-pro')!
    return all.filter((p) => p.sweepKey === t.sweepKey)
  }

  it('one sweep per row: no sweep column and no repeat note', () => {
    const { html } = render(<PointsTable points={pts()} title="t" />)
    expect(html).not.toContain('InferenceX sweep')
    expect(html).not.toContain('Repeated rows')
    expect(html).not.toContain('different vLLM builds')
  })

  it('a repeated concurrency numbers its sweeps and says what they are', () => {
    const one = pts()
    const twin = one.map((p) => ({ ...p, sweepId: `${p.sweepId}|b`, pointId: `${p.pointId}b` }))
    const { html } = render(<PointsTable points={[...one, ...twin]} title="t" />)
    expect(html).toContain('InferenceX sweep')
    expect(html).toContain('separate InferenceX sweeps of this deployment')
    // each concurrency lists sweep 1 before sweep 2
    const nums = [...html.matchAll(/\d{4}-\d\d-\d\d<\/td><td class="mono">([12])<\/td>/g)].map((m) => m[1])
    expect(nums.length).toBe(2 * one.length)
    expect(nums.join('')).toMatch(/^(12)+$/)
    expect(html).not.toContain('different vLLM builds')
  })
})

describe('a GPU row names a precision only when its deployments share one', () => {
  it('leaves it blank for a GPU serving two precisions', () => {
    const s = v2a()
    const g = s.matrix.find((m) => m.model === 'deepseek-v4-pro')!.rows[0]!.rows[0]!
    const t = g.rows[0]!
    g.rows.push({ ...t, precision: 'fp8', label: t.label.replace('fp4', 'fp8'), rows: t.rows.map((p) => ({ ...p, point_id: `${p.point_id}x` })) })
    g.precision = null
    const all = flattenPoints(s).filter((p) => p.model === 'deepseek-v4-pro')
    expect(new Set(all.map((p) => p.precision))).toEqual(new Set(['fp4', 'fp8']))
    const wl = all[0]!.workloadLabel
    const rows = buildRows(all, new Set(['m:deepseek-v4-pro', `m:deepseek-v4-pro|w:${wl}`]))
    const gpu = rows.find((r) => r.level === 'gpu')!
    expect(gpu.facet).toBe('')
    // and a GPU whose deployments share one still names it
    const same = buildRows(flattenPoints(v2a()).filter((p) => p.model === 'deepseek-v4-pro'),
      new Set(['m:deepseek-v4-pro', `m:deepseek-v4-pro|w:${wl}`]))
    expect(same.find((r) => r.level === 'gpu')!.facet).toBe('fp4')
  })
})

describe('Compare counts a point in the exact tier only when both runs call it exact', () => {
  it('drops a pair whose status differs between the runs', () => {
    const a = v2a()
    const b = v2b()
    const html = (x: Summary, y: Summary) =>
      render(<Compare a={x} b={y} tier="measured_or_resolved" />).html
    const before = html(a, b)
    // Mark one shared exact point estimated in run-b only: the strict Δ must leave it out on BOTH
    // sides, so the result equals dropping that point from both runs.
    const shared = intersectByKey(flattenPoints(a), flattenPoints(b)).pairs.find((p) => p.a.tier === 'measured_or_resolved')!
    const flip = (s: Summary, id: string, tier: 'all' | 'measured_or_resolved') => {
      for (const m of s.matrix) for (const w of m.rows) for (const g of w.rows) for (const t of g.rows)
        for (const p of t.rows) if (p.point_id === id) p.tier = tier
    }
    const b2 = v2b()
    flip(b2, shared.key, 'all')
    const a2 = v2a()
    flip(a2, shared.key, 'all')
    expect(html(a, b2)).toEqual(html(a2, b2))
    expect(html(a, b2)).not.toEqual(before)
  })
})
