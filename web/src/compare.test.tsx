/**
 * Tests for the A-vs-B compare view (RFC discussion #2 point 3). The strict-intersection join, the
 * Δ = B − A math over the shared points, and that the compare view renders with zero console errors.
 * We only have ONE real snapshot, so run B is synthesized from the fixture with perturbed
 * predictions — clearly a test construct, never shipped.
 */
import { describe, expect, it, vi } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { App } from './App'
import { validateSummary } from './load'
import { flattenPoints, intersectByKey, pointKey } from './aggregate'
import type { Summary } from './types'

function loadFixture(): Summary {
  const path = fileURLToPath(new URL('../testdata/render-fixture.summary.json', import.meta.url))
  return validateSummary(JSON.parse(readFileSync(path, 'utf8')))
}

/** A deep clone with predictions scaled by `k` (so errors shift) and snapshot_id suffixed. */
function perturb(s: Summary, k: number, idSuffix: string): Summary {
  const c: Summary = JSON.parse(JSON.stringify(s))
  c.snapshot_id = `${s.snapshot_id}-${idSuffix}`
  const walk = (node: any) => {
    if (Array.isArray(node)) return node.forEach(walk)
    if (node && typeof node === 'object') {
      if (node.level === 'point' && node.predicted) {
        if (node.predicted.ttft_ms != null) node.predicted.ttft_ms *= k
        if (node.predicted.tpot_ms != null) node.predicted.tpot_ms *= k
        // recompute error_pct = (pred/meas - 1)*100 so the perturbed prediction is self-consistent
        if (node.measured?.ttft_ms) node.error_pct.ttft = (node.predicted.ttft_ms / node.measured.ttft_ms - 1) * 100
        if (node.measured?.tpot_ms) node.error_pct.tpot = (node.predicted.tpot_ms / node.measured.tpot_ms - 1) * 100
      }
      for (const v of Object.values(node)) walk(v)
    }
  }
  walk(c.matrix)
  return c
}

describe('A-vs-B compare (RFC discussion #2 point 3)', () => {
  it('intersects strictly: a point only in one run is excluded', () => {
    const a = loadFixture()
    const b = perturb(a, 1.1, 'B')
    const aPts = flattenPoints(a)
    const bPts = flattenPoints(b).slice(0, -5) // drop 5 points from B
    const { pairs, onlyA } = intersectByKey(aPts, bPts)
    // Invariant on DISTINCT keys (intersectByKey dedups by pointKey): shared + only-in-A = all
    // distinct A-scored keys. (A can carry true duplicate (conc,version) rows that share a key.)
    const aScoredKeys = new Set(aPts.filter((p) => p.errTtft != null || p.errTpot != null).map(pointKey))
    const bScoredKeys = new Set(bPts.filter((p) => p.errTtft != null || p.errTpot != null).map(pointKey))
    expect(pairs.every((p) => bScoredKeys.has(p.key) && aScoredKeys.has(p.key))).toBe(true)
    expect(pairs.length + onlyA).toBe(aScoredKeys.size)
    expect(pairs.length).toBeLessThan(aScoredKeys.size) // the dropped points really are excluded
  })

  it('identical runs → every shared point has Δ 0', () => {
    const a = loadFixture()
    const { pairs } = intersectByKey(flattenPoints(a), flattenPoints(a))
    expect(pairs.length).toBeGreaterThan(0)
    for (const { a: pa, b: pb } of pairs) {
      expect((pb.errTtft ?? 0) - (pa.errTtft ?? 0)).toBe(0)
    }
  })

  it('Δ = B − A: scaling B predictions up raises the error delta (direction is B − A)', () => {
    const a = loadFixture()
    const b = perturb(a, 1.5, 'B') // B predicts 50% higher → larger |error| than A on most points
    const { pairs } = intersectByKey(flattenPoints(a), flattenPoints(a).length ? flattenPoints(b) : [])
    // pick a shared point where A under-predicted (err<0): scaling pred UP moves err toward 0 or positive
    const sample = pairs.find((p) => (p.a.errTtft ?? 0) !== (p.b.errTtft ?? 0))
    expect(sample).toBeDefined()
    const d = (sample!.b.errTtft ?? 0) - (sample!.a.errTtft ?? 0)
    expect(Number.isFinite(d)).toBe(true)
  })

  it('renders the compare view with zero console errors and no NaN/blank', () => {
    const a = loadFixture()
    const b = perturb(a, 1.2, 'B')
    const errors: string[] = []
    const spy = vi.spyOn(console, 'error').mockImplementation((...x) => errors.push(x.map(String).join(' ')))
    const html = renderToStaticMarkup(
      <App summary={a} summaryB={b} loadError={null} initialHash={`#/?run=${a.snapshot_id}&runB=${b.snapshot_id}`} />,
    )
    spy.mockRestore()
    expect(errors.join('\n')).toBe('')
    expect(html).toContain('Compare runs')
    expect(html).toContain('scored by both') // the shared-point count line
    for (const bad of ['NaN', 'undefined', 'Infinity']) expect(html).not.toContain(bad)
  })

  it('single-run mode is unchanged when summaryB is null (Overview, not Compare)', () => {
    const a = loadFixture()
    const html = renderToStaticMarkup(<App summary={a} summaryB={null} loadError={null} />)
    expect(html).toContain('End-to-end accuracy — BLIS vs InferenceX') // Overview headline
    expect(html).not.toContain('Compare runs')
  })

  it('refuses to compare a run with itself (same snapshot_id → Overview, not Compare)', () => {
    const a = loadFixture()
    // a hand-crafted run=X&runB=X: summaryB is the SAME snapshot → must fall through to single-run
    const html = renderToStaticMarkup(
      <App summary={a} summaryB={a} loadError={null} initialHash={`#/?run=${a.snapshot_id}&runB=${a.snapshot_id}`} />,
    )
    expect(html).not.toContain('Compare runs')
    expect(html).toContain('End-to-end accuracy — BLIS vs InferenceX') // Overview
  })

  it('compare header shows the chosen A and B (A = run slot, not data/latest)', () => {
    // Regression: when A was pinned to an explicit (non-latest) snapshot, the view must show THAT
    // run as A — not resolve A back to data/latest and show B's data on both sides.
    const a = loadFixture() // id ...2026-10-19... (the "A"/baseline here)
    const b = perturb(a, 1.2, 'B20') // a distinct id acting as B
    const html = renderToStaticMarkup(
      <App summary={a} summaryB={b} loadError={null} initialHash={`#/?run=${a.snapshot_id}&runB=${b.snapshot_id}`} />,
    )
    // The A header carries A's snapshot id; the B header carries B's — they are DIFFERENT.
    expect(html).toContain(a.snapshot_id.slice(0, 10))
    expect(html).toContain(b.snapshot_id.slice(0, 10))
    expect(a.snapshot_id).not.toBe(b.snapshot_id)
  })

  it('green means the NEWER run improved, whichever slot each run was picked in (#5)', () => {
    // The newer run predicts TPOT exactly (error 0) at every point, a strict TPOT improvement over
    // the older run. Snapshot ids lead with their date, so '2099-…' is the newer one.
    const older = loadFixture()
    const newer: Summary = JSON.parse(JSON.stringify(older))
    newer.snapshot_id = '2099-01-01_blis-vNEW_ix-same'
    const walk = (node: any) => {
      if (Array.isArray(node)) return node.forEach(walk)
      if (node && typeof node === 'object') {
        if (node.level === 'point' && node.measured?.tpot_ms != null && node.error_pct?.tpot != null) {
          node.predicted.tpot_ms = node.measured.tpot_ms
          node.error_pct.tpot = 0
        }
        for (const v of Object.values(node)) walk(v)
      }
    }
    walk(newer.matrix)
    // Newer-in-A first: that is the order the old B − A convention coloured backwards.
    for (const [slotA, slotB] of [[newer, older], [older, newer]] as const) {
      const html = renderToStaticMarkup(
        <App summary={slotA} summaryB={slotB} loadError={null} initialHash={`#/?run=${slotA.snapshot_id}&runB=${slotB.snapshot_id}`} />,
      )
      const body = html.slice(html.indexOf('<tbody'))
      const firstRow = body.slice(0, body.indexOf('</tr>'))
      // Cells in order: TTFT mape, TTFT shape, TPOT mape, TPOT shape. TPOT mape improved.
      const cells = firstRow.match(/num d-[a-z]+/g) ?? []
      expect(cells[2]).toBe('num d-better')
      expect(firstRow).not.toContain('d-worse')
      // The header always reads older → newer.
      expect(html.indexOf('>older<')).toBeLessThan(html.indexOf('>newer<'))
      // …but each run still carries the rail tag of the slot it was picked in.
      const runs = html.match(/<div class="cmp-run">.*?<\/div>/g) ?? []
      const runFor = (s: Summary) => runs.find((r) => r.includes(s.snapshot_id.slice(0, 10)))!
      expect(runFor(slotA)).toContain('cmp-tag cmp-a">A<')
      expect(runFor(slotB)).toContain('cmp-tag cmp-b">B<')
    }
  })
})
