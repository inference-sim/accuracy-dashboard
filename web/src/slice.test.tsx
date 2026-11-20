/**
 * COV-13 (design v4.2.0): a slice can be cut by any recorded attribute of a scored unit, and no
 * aggregate is shown at any level, headline to a drilled-in slice, over fewer than min_points
 * ROLE KEYS (not points). The count is shown in its place, the point rows stay visible, and the
 * per-point table states the rule.
 */
import { describe, expect, it, vi } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { App } from './App'
import { validateSummary } from './load'
import { aggregatePair, flattenPoints, roleKeyOf, type FlatPoint } from './aggregate'
import { applyFilters } from './filter'
import { DEFAULT_ROUTE, parseRoute, routeToHash } from './route'
import { gateHeadline, MIN_ROLE_KEYS, SLICE_ATTRS, sliceBy, UNRECORDED } from './slice'
import { Slices } from './components/Slices'
import { PointsTable } from './components/PointsTable'
import { buildRows } from './tree'
import { TOO_FEW, type HeadlineBlock, type Summary, type UnitIdentity } from './types'

const fixture = (): Summary =>
  validateSummary(
    JSON.parse(readFileSync(fileURLToPath(new URL('../testdata/render-fixture.v3.summary.json', import.meta.url)), 'utf8')),
  )

const IDENTITY: UnitIdentity = {
  source: 'inferencex',
  model: 'dsv4',
  hardware: 'b200',
  precision: 'fp4',
  framework: 'vllm',
  benchmark_type: 'single_turn',
  configuration_hash: 'c0',
  recipe_fingerprint: null,
  conc: 1,
  measured_date: '2026-09-03',
  benchmark_run: null,
}

/** A scored point of the role key `k` (one deployment under one benchmark type). */
function point(i: number, k: number, over: Partial<FlatPoint> = {}): FlatPoint {
  const base = flattenPoints(fixture())[0]!
  return {
    ...base,
    pointId: `p${i}`,
    concurrency: i + 1,
    errTtft: 10 + i,
    errTpot: 5 + i,
    shapeTtft: null,
    shapeTpot: null,
    identity: { ...IDENTITY, configuration_hash: `c${k}`, conc: i + 1 },
    ...over,
  }
}

/** `points` points spread over `keys` role keys. */
const pts = (points: number, keys: number, over: Partial<FlatPoint> = {}) =>
  Array.from({ length: points }, (_, i) => point(i, i % keys, over))

function render(el: React.ReactElement): { html: string; errors: string[] } {
  const errors: string[] = []
  const spy = vi.spyOn(console, 'error').mockImplementation((...a) => {
    errors.push(a.map(String).join(' '))
  })
  const html = renderToStaticMarkup(el)
  spy.mockRestore()
  return { html, errors }
}

describe('the role key (design Table 1.4)', () => {
  const k = (id: Partial<UnitIdentity>) => roleKeyOf(point(0, 0, { identity: { ...IDENTITY, ...id } }))

  it('is one deployment under one benchmark type, whatever the concurrency, date or run', () => {
    const same = k({})
    expect(k({ conc: 64 })).toBe(same)
    expect(k({ measured_date: '2026-10-01' })).toBe(same)
    expect(k({ benchmark_run: 7 })).toBe(same)
  })

  it.each([
    ['source', { source: 'other' as unknown as 'inferencex' }],
    ['model', { model: 'dsv41flash' }],
    ['hardware', { hardware: 'h200' }],
    ['precision', { precision: 'fp8' }],
    ['framework', { framework: 'sglang' }],
    ['benchmark type', { benchmark_type: 'agentic_traces' }],
    ['configuration hash', { configuration_hash: 'c9' }],
  ])('differs when the %s differs', (_, change) => {
    expect(k(change)).not.toBe(k({}))
  })

  it('reads a legacy identity (a snapshot published before unit ids) as the same deployment', () => {
    const { configuration_hash: _c, recipe_fingerprint: _r, source: _s, benchmark_run: _b, ...rest } = IDENTITY
    const legacy = roleKeyOf(point(0, 0, { identity: { ...rest, recipe: 'c0' } }))
    expect(legacy).toBe(k({}))
  })
})

describe('an aggregate over fewer than min_points role keys shows no figure (COV-13)', () => {
  it.each([
    { points: 10, keys: 1, shown: false },
    { points: 10, keys: 2, shown: false },
    { points: 40, keys: 9, shown: false },
    { points: 10, keys: 10, shown: true },
    { points: 25, keys: 10, shown: true },
    { points: 9, keys: 9, shown: false },
  ])('$points points from $keys role keys: figure shown = $shown', ({ points, keys, shown }) => {
    const m = aggregatePair(pts(points, keys), MIN_ROLE_KEYS).all.mape
    expect(m.ttft === TOO_FEW).toBe(!shown)
    expect(m.tpot === TOO_FEW).toBe(!shown)
    expect(m.n).toBe(points)
    expect(m.roleKeys).toBe(keys)
  })

  it('counts only the role keys that hold the value', () => {
    const p = [...pts(10, 2), point(10, 5, { errTpot: null })]
    const m = aggregatePair(p, 10).all.mape
    expect(m.roleKeys).toBe(3)
    expect(m.tpot).toBe(TOO_FEW)
  })

  it('leaves v1 and v2 snapshots, which pass no minimum, as they were', () => {
    expect(aggregatePair(pts(10, 2)).all.mape.ttft).toEqual(expect.any(Number))
  })

  it('applies to every row of the tree, the model row down', () => {
    const rows = buildRows(pts(10, 2), new Set(), 10)
    expect(rows[0]!.metrics.all.mape.ttft).toBe(TOO_FEW)
    expect(rows[0]!.pointCount).toBe(10)
  })
})

describe('slicing by any recorded attribute', () => {
  const mixed = () => [
    ...pts(10, 2, { gpu: 'h200' }).map((p, i) => ({ ...p, pointId: `a${i}` })),
    ...pts(12, 12, { gpu: 'b200' }).map((p, i) => ({ ...p, pointId: `b${i}`, identity: { ...IDENTITY, configuration_hash: `z${i}` } })),
  ]

  it('ten points from two role keys render no aggregate, and the slice still lists its units', () => {
    const rows = sliceBy(mixed(), 'chip', 10)
    const small = rows.find((r) => r.value === 'h200')!
    expect(small).toMatchObject({ points: 10, roleKeys: 2, shown: false, ttft: TOO_FEW, tpot: TOO_FEW })
    expect(small.reason).toContain('2 role keys')
    expect(small.reason).toContain('10')
    expect(small.units).toHaveLength(10)
    const big = rows.find((r) => r.value === 'b200')!
    expect(big).toMatchObject({ points: 12, roleKeys: 12, shown: true })
    expect(big.ttft).toEqual(expect.any(Number))
  })

  it('shows the slice figure as the mean of its points, not of the other slices', () => {
    const big = sliceBy(mixed(), 'chip', 10).find((r) => r.value === 'b200')!
    const errs = Array.from({ length: 12 }, (_, i) => 10 + i)
    expect(big.ttft).toBeCloseTo(errs.reduce((a, b) => a + b, 0) / 12)
  })

  it('orders slices by point count, largest first, then by value', () => {
    expect(sliceBy(mixed(), 'chip', 10).map((r) => r.value)).toEqual(['b200', 'h200'])
  })

  it('puts a point with several substitutions in each of their slices, and one with none in "none"', () => {
    const sub = (kind: string) => ({ kind, subject: 's', detail: 'd' })
    const base = point(0, 0)
    const p = [
      { ...base, fidelity: { ...base.fidelity!, substitutions: [sub('a'), sub('b')] } },
      { ...point(1, 1), fidelity: { ...base.fidelity!, substitutions: [] } },
    ]
    const rows = sliceBy(p, 'substitution', 10)
    expect(rows.map((r) => [r.value, r.points])).toEqual([['a', 1], ['b', 1], ['none', 1]])
  })

  it('takes coverage from the not-scored points where they record the attribute', () => {
    const rows = sliceBy(mixed(), 'chip', 10, [{ hardware: 'h200' }, { hardware: 'h200' }, { hardware: 'b200' }])
    expect(rows.find((r) => r.value === 'h200')!.coverage).toEqual({ scored: 10, total: 12 })
    expect(rows.find((r) => r.value === 'b200')!.coverage).toEqual({ scored: 12, total: 13 })
    expect(sliceBy(mixed(), 'engine', 10, [{ hardware: 'h200' }])[0]!.coverage).toBeNull()
  })

  it('cuts the flattened fixture by every attribute without losing a point', () => {
    const all = flattenPoints(fixture())
    for (const a of SLICE_ATTRS) {
      const rows = sliceBy(all, a.id, 10)
      const total = rows.reduce((n, r) => n + r.points, 0)
      expect(total, a.id).toBeGreaterThanOrEqual(all.length)
      if (a.id !== 'substitution') expect(total, a.id).toBe(all.length)
      for (const r of rows) expect(r.shown, `${a.id}=${r.value}`).toBe(false)
    }
  })

  it('names the attributes a point does not record yet instead of dropping them', () => {
    expect(UNRECORDED.map((u) => u.id)).toEqual(
      expect.arrayContaining(['node_count', 'interconnect', 'offload', 'router', 'arrival', 'prefix', 'source_revision']),
    )
    for (const u of UNRECORDED) expect(SLICE_ATTRS.some((a) => a.id === u.id)).toBe(false)
  })
})

describe('the slice view', () => {
  const points = [...pts(10, 2, { gpu: 'h200' })]

  it('renders no figure for a slice of ten points from two role keys, the count in its place', () => {
    const { html, errors } = render(
      <Slices points={points} by="chip" sv={null} min={10} notScored={[]} onBy={() => {}} onSv={() => {}} />,
    )
    expect(errors.join('\n')).toBe('')
    expect(html).toContain('2 role keys')
    expect(html).toContain('<td>too few points (2 role keys)</td><td>too few points (2 role keys)</td>')
    expect(html).not.toMatch(/<td[^>]*>\d+\.\d%<\/td>/)
    expect(html).toContain('h200')
    for (let i = 0; i < 10; i++) expect(html).toContain(`p${i}`)
    expect(html).toMatch(/fewer than 10 role keys/)
  })

  it('renders the figure for a slice of enough role keys', () => {
    const html = render(
      <Slices points={pts(10, 10)} by="chip" sv={null} min={10} notScored={[]} onBy={() => {}} onSv={() => {}} />,
    ).html
    expect(html).toMatch(/\d+\.\d%/)
    expect(html).not.toContain('too few points')
  })

  it('lists every sliceable attribute in the selector and the ones not recorded yet', () => {
    const html = render(
      <Slices points={points} by="chip" sv={null} min={10} notScored={[]} onBy={() => {}} onSv={() => {}} />,
    ).html
    for (const a of SLICE_ATTRS) expect(html).toContain(`value="${a.id}"`)
    for (const u of UNRECORDED) expect(html).toContain(u.label)
  })
})

describe('the per-point table states the rule and keeps every row', () => {
  it('shows all ten point rows with the rule beside them', () => {
    const p = pts(10, 2)
    const html = render(<PointsTable points={p} title="t" minRoleKeys={10} />).html
    expect((html.match(/<tr key|<td class="mono">/g) ?? []).length).toBeGreaterThanOrEqual(10)
    expect(html).toMatch(/fewer than 10 role keys/)
  })

  it('says nothing about the rule where no minimum applies (v1, v2)', () => {
    expect(render(<PointsTable points={pts(3, 1)} title="t" />).html).not.toContain('role keys')
  })
})

describe('the route carries the slice', () => {
  it('round-trips by and sv', () => {
    const r = { ...DEFAULT_ROUTE, by: 'chip', sv: 'h200 b' }
    expect(parseRoute(routeToHash(r))).toEqual(r)
    expect(routeToHash(DEFAULT_ROUTE)).toBe('#/')
  })

  it('ignores a slice value without an attribute, and an unknown attribute', () => {
    expect(parseRoute('#/?sv=h200')).toEqual(DEFAULT_ROUTE)
    expect(parseRoute('#/?by=nonsense&sv=x')).toEqual(DEFAULT_ROUTE)
  })

  it('keeps only the points of the drilled-in slice, so every aggregate under it is that slice\'s', () => {
    const mix = [...pts(10, 2, { gpu: 'h200' }), ...pts(12, 12, { gpu: 'b200' })]
    const kept = applyFilters(mix, { ...DEFAULT_ROUTE, by: 'chip', sv: 'h200' })
    expect(kept).toHaveLength(10)
    expect(kept.every((p) => p.gpu === 'h200')).toBe(true)
    expect(applyFilters(mix, { ...DEFAULT_ROUTE, by: 'chip' })).toHaveLength(22)
  })
})

describe('the headline follows the same rule', () => {
  const block = (): HeadlineBlock => ({
    points: 14,
    graded: 10,
    not_scored: 4,
    headline: { ttft: { mape: 12, n: 10 }, tpot: { mape: 6, n: 10 } },
    grades: {
      G1: { points: 0, share: 0, ttft: { mape: TOO_FEW, n: 0 }, tpot: { mape: TOO_FEW, n: 0 } },
      G2: { points: 10, share: 1, ttft: { mape: 12, n: 10 }, tpot: { mape: 6, n: 10 } },
      G3: { points: 0, share: 0, ttft: { mape: TOO_FEW, n: 0 }, tpot: { mape: TOO_FEW, n: 0 } },
      G4: { points: 0, share: 0, ttft: { mape: TOO_FEW, n: 0 }, tpot: { mape: TOO_FEW, n: 0 } },
    },
  })
  const graded = (p: FlatPoint[], grade: 'G2') =>
    p.map((x) => ({ ...x, fidelity: { ...x.fidelity!, grade } }))

  it('withholds the figure published over ten points from two role keys', () => {
    const g = gateHeadline(block(), graded(pts(10, 2), 'G2'), 10)
    expect(g.headline.ttft).toEqual({ mape: TOO_FEW, n: 10, roleKeys: 2 })
    expect(g.headline.tpot).toEqual({ mape: TOO_FEW, n: 10, roleKeys: 2 })
    expect(g.grades.G2.ttft.mape).toBe(TOO_FEW)
    expect(g.grades.G2.share).toBe(TOO_FEW)
    expect(g.graded).toBe(10)
  })

  it('keeps it over ten role keys', () => {
    const g = gateHeadline(block(), graded(pts(10, 10), 'G2'), 10)
    expect(g.headline.ttft).toEqual({ mape: 12, n: 10, roleKeys: 10 })
    expect(g.grades.G2.share).toBe(1)
  })

  it('gates each grade by its own role keys', () => {
    const b = block()
    b.grades.G1 = { points: 10, share: 0.5, ttft: { mape: 3, n: 10 }, tpot: { mape: 2, n: 10 } }
    const p = [...pts(10, 10).map((x) => ({ ...x, fidelity: { ...x.fidelity!, grade: 'G1' as const } })), ...graded(pts(10, 2), 'G2')]
    const g = gateHeadline(b, p, 10)
    expect(g.grades.G1.ttft.mape).toBe(3)
    expect(g.grades.G2.ttft.mape).toBe(TOO_FEW)
  })
})

describe('the page', () => {
  it('offers the slices on a v3 snapshot and states the rule beside the points', () => {
    const { html, errors } = render(<App summary={fixture()} loadError={null} initialHash="#/?by=chip" />)
    expect(errors.join('\n')).toBe('')
    expect(html).toContain('Accuracy by slice')
    expect(html).toContain('role keys')
    expect(html).not.toContain('NaN')
  })

  it('drills into a slice: its tree rows are that slice\'s alone', () => {
    const s = fixture()
    const chip = flattenPoints(s)[0]!.gpu
    const html = render(<App summary={s} loadError={null} initialHash={`#/?by=chip&sv=${encodeURIComponent(chip)}`} />).html
    expect(html).toContain(chip)
    expect(html).toContain('slice-drill')
  })
})
