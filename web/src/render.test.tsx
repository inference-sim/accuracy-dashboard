/**
 * Headless render tests (vitest + renderToStaticMarkup, environment: 'node') — the stand-in
 * for "npm run dev and look". They assert the real snapshot renders with ZERO console errors
 * and no NaN/blank cells (RFC B1), and that the deep-link / tier / filter logic behaves.
 */
import { describe, expect, it, vi } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { App } from './App'
import { validateSummary } from './load'
import { flattenPoints, aggregatePair } from './aggregate'
import { applyFilters } from './filter'
import type { Summary } from './types'

function loadFixture(): Summary {
  // A real signedprobe-derived snapshot, committed as a labeled test fixture. The SHIPPED
  // data/latest/summary.json is only ever CI-produced (RFC D2); this is not that file.
  const path = fileURLToPath(new URL('../testdata/render-fixture.summary.json', import.meta.url))
  return validateSummary(JSON.parse(readFileSync(path, 'utf8')))
}

describe('App renders the real CI-shaped snapshot', () => {
  it('renders with zero console errors and no NaN/undefined in the DOM', () => {
    const errors: string[] = []
    const spy = vi.spyOn(console, 'error').mockImplementation((...a) => {
      errors.push(a.map(String).join(' '))
    })
    const html = renderToStaticMarkup(<App summary={loadFixture()} loadError={null} />)
    spy.mockRestore()
    expect(errors.join('\n')).toBe('')
    expect(html).not.toContain('NaN')
    expect(html).not.toContain('undefined')
    expect(html).not.toContain('>null<')
  })

  it('renders a selected topology points table with zero console errors (React-key safety)', () => {
    // The points table keys rows by `${concurrency}-${i}`, not concurrency alone, so it is safe
    // even if a topology ever carries repeat measurements at one concurrency (same deployment
    // measured twice). The latest-N filter + precision-separated topology grouping mean the
    // current fixture has one row per concurrency, but the key safety must still hold. Select the
    // first real topology and assert no console errors (incl. no "two children with same key").
    const summary = loadFixture()
    let sweepKey = ''
    outer: for (const m of summary.matrix)
      for (const w of m.rows)
        for (const g of w.rows)
          for (const t of g.rows) {
            sweepKey = `${m.model}|${w.label}|${g.label}|${t.label}`
            break outer
          }
    expect(sweepKey).not.toBe('') // the fixture has at least one topology
    const errors: string[] = []
    const spy = vi.spyOn(console, 'error').mockImplementation((...a) => {
      errors.push(a.map(String).join(' '))
    })
    renderToStaticMarkup(
      <App summary={summary} loadError={null} initialHash={`#/?sel=${encodeURIComponent(sweepKey)}&tier=all`} />,
    )
    spy.mockRestore()
    expect(errors.join('\n')).toBe('') // no "two children with the same key" warning
  })

  it('shows the headline totals row and the title', () => {
    const html = renderToStaticMarkup(<App summary={loadFixture()} loadError={null} />)
    expect(html).toContain('ALL MODELS')
    expect(html).toContain('End-to-end accuracy — BLIS vs InferenceX')
  })

  it('renders every model when the populated tier is viewed (via deep-link)', () => {
    // The direct path leaves settings resolved, so every point lands in the "all" tier (zero in
    // measured·resolved). Every model must still render. Drive to the "all" tier via deep-link.
    const html = renderToStaticMarkup(<App summary={loadFixture()} loadError={null} initialHash="#/?tier=all" />)
    expect(html).toContain('deepseek-v4-pro')
    expect(html).toContain('gpt-oss-120b')
    expect(html).toContain('kimi-k2.5')
    expect(html).toContain('minimax-m2.5')
  })

  it('falls back to the all tier (with a banner) when measured·resolved is empty', () => {
    // Default tier = measured·resolved; the real snapshot has zero such points (direct path), so
    // the UI must not show an empty headline — it falls back to the all tier and says so.
    const html = renderToStaticMarkup(<App summary={loadFixture()} loadError={null} />)
    expect(html).toContain('no measured·resolved points — showing all')
    expect(html).toContain('deepseek-v4-pro') // data visible, not an empty table
  })

  it('a deep-linked selected topology populates the points table with measured vs predicted', () => {
    const summary = loadFixture()
    // first topology sweepKey from the fixture
    const m = summary.matrix[0]!
    const w = m.rows[0]!
    const g = w.rows[0]!
    const t = g.rows[0]!
    const sweepKey = `${m.model}|${w.label}|${g.label}|${t.label}`
    const hash = `#/?sel=${encodeURIComponent(sweepKey)}&tier=all`
    const html = renderToStaticMarkup(<App summary={summary} loadError={null} initialHash={hash} />)
    expect(html).toContain('Points — ')
    expect(html).toContain(m.model)
    // the points table header
    expect(html).toContain('meas')
    expect(html).toContain('pred')
  })

  it('shows the provenance rail from the summary (not hardcoded)', () => {
    const html = renderToStaticMarkup(<App summary={loadFixture()} loadError={null} />)
    expect(html).toContain('v0.10.0') // resolved BLIS release
    expect(html).toContain('0.2.1') // catalog
    expect(html).toContain('v0.1.1') // registry
    expect(html).toContain('2026-09-28') // dump tag
  })

  it('shows the future-metrics note and run-wide counts', () => {
    const html = renderToStaticMarkup(<App summary={loadFixture()} loadError={null} />)
    expect(html).toContain('E2E, tail-latency and throughput accuracy are planned for a future release')
    expect(html).toContain('points scored')
    expect(html).toContain('not scored')
    expect(html).toContain('multi-node')
  })

  it('renders a clear error (not a blank page) when loading fails', () => {
    const html = renderToStaticMarkup(<App summary={null} loadError={'fetching data/latest/summary.json returned HTTP 404'} />)
    expect(html).toContain('Could not load this snapshot')
    expect(html).toContain('HTTP 404')
  })

  it('renders the nightly run-picker when an index with >1 run is supplied', () => {
    const index = {
      schema_version: 1 as const,
      latest: 'b',
      retention_days: 30,
      runs: [
        { snapshot_id: 'b', generated_at: null, blis_release: 'v0.10.0', ix_release: 'db-dump/2026-09-28', path: 'snapshots/b/summary.json' },
        { snapshot_id: 'a', generated_at: null, blis_release: 'v0.10.0', ix_release: 'db-dump/2026-09-21', path: 'snapshots/a/summary.json' },
      ],
    }
    const html = renderToStaticMarkup(<App summary={loadFixture()} loadError={null} index={index} />)
    expect(html).toContain('Nightly run')
    expect(html).toContain('does not re-run')
    // the picker is the styled dropdown (native <select> replaced per jgchn review); it shows the
    // latest run's label and is interactive (not disabled) when >1 run exists
    expect(html).toContain('dd-trigger box runsel')
    expect(html).toContain('aria-label="Select the nightly run (A)"')
    expect(html).not.toContain('aria-label="Select the nightly run (A)" disabled')
  })

  it('omits the run-picker entirely when there is no index', () => {
    const html = renderToStaticMarkup(<App summary={loadFixture()} loadError={null} index={null} />)
    expect(html).not.toContain('Nightly run')
  })

  it('shows the run-picker (disabled, no "re-run" note) for a single-run index', () => {
    const index = {
      schema_version: 1 as const,
      latest: 'a',
      retention_days: 30,
      runs: [{ snapshot_id: 'a', generated_at: null, blis_release: 'v0.10.0', ix_release: 'db-dump/2026-09-28', path: 'snapshots/a/summary.json' }],
    }
    const html = renderToStaticMarkup(<App summary={loadFixture()} loadError={null} index={index} />)
    expect(html).toContain('Nightly run') // picker shown as provenance
    expect(html).toContain('disabled') // but not interactive with only one run
    expect(html).not.toContain('does not re-run') // note only when there are older runs
  })
})

describe('client-side aggregation keeps filters honest (RFC B3)', () => {
  it('a specific-version filter isolates that version; "all" shows every version', () => {
    const summary = loadFixture()
    const all = flattenPoints(summary)
    const version = all.find((p) => p.engineVersion)!.engineVersion!
    const allVersions = applyFilters(all, { run: null, runB: null, sel: null, tier: 'all', vllm: 'all', multinode: false })
    const pinned = applyFilters(all, { run: null, runB: null, sel: null, tier: 'all', vllm: { version }, multinode: false })
    expect(pinned.length).toBeLessThanOrEqual(allVersions.length)
    expect(pinned.every((p) => p.engineVersion === version)).toBe(true)
  })

  it('a version filter changes the RENDERED headline number (not just subset size) — T-b', () => {
    const summary = loadFixture()
    const all = flattenPoints(summary)
    // pick a version that is NOT the only one, so filtering genuinely changes the mean
    const versions = [...new Set(all.map((p) => p.engineVersion).filter(Boolean))]
    const version = versions.find((v) => all.filter((p) => p.engineVersion === v).length < all.length)!
    // hand-compute the expected all-tier TTFT MAPE over just that version's points
    const pinnedPts = all.filter((p) => p.engineVersion === version)
    const errs = pinnedPts.map((p) => p.errTtft).filter((e): e is number => e != null)
    const expected = errs.reduce((a, e) => a + Math.abs(e), 0) / errs.length
    // render App with that version pinned + the all tier, and read the headline TTFT mape cell
    const hash = `#/?tier=all&vllm=${encodeURIComponent('v:' + version)}`
    const html = renderToStaticMarkup(<App summary={summary} loadError={null} initialHash={hash} />)
    // the totals row renders mape as e.g. "32.9%"; assert the hand-computed mean appears
    const want = `${expected.toLocaleString('en-US', { minimumFractionDigits: 1, maximumFractionDigits: 1 })}%`
    expect(html).toContain(want)
  })

  it('totals recompute from visible points (not the stored node metrics)', () => {
    const summary = loadFixture()
    const all = flattenPoints(summary)
    const half = all.slice(0, Math.floor(all.length / 2))
    const full = aggregatePair(all)
    const partial = aggregatePair(half)
    // A different subset generally yields a different mean — proving it's recomputed, not stored.
    expect(partial.all.mape.n).toBeLessThan(full.all.mape.n)
  })
})
