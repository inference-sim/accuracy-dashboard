// Browser smoke for a v2 snapshot (#30): load the site in headless Chromium and fail on any
// console error / page error / failed request, then drive the v2 parts: drill down to a
// deployment, check the measured-date column and a provenance mark per point, open a provenance
// tooltip by keyboard focus and check its content, and confirm not-scored points never render.
// Optionally (SHOTS=dir) save screenshots of each step.
//
//   npm run build   (with a v2 summary staged in public/data)  then  node smoke_v2.mjs
//   SMOKE_URL=http://localhost:5173 node smoke_v2.mjs     against a running dev server
import { createServer } from 'node:http'
import { readFile, stat } from 'node:fs/promises'
import { extname, join, normalize } from 'node:path'
import { chromium } from 'playwright'

const EXTERNAL = process.env.SMOKE_URL || ''
const SHOTS = process.env.SHOTS || ''
const ROOT = normalize(join(process.cwd(), 'dist'))
const PORT = 4874
const BASE = EXTERNAL || `http://localhost:${PORT}`
const MIME = { '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.json': 'application/json', '.svg': 'image/svg+xml' }

const server = EXTERNAL
  ? null
  : createServer(async (req, res) => {
      try {
        let p = decodeURIComponent((req.url || '/').split('?')[0])
        if (p === '/') p = '/index.html'
        const full = normalize(join(ROOT, p))
        if (!full.startsWith(ROOT)) return void res.writeHead(403).end()
        await stat(full)
        res.writeHead(200, { 'content-type': MIME[extname(full)] || 'application/octet-stream' })
        res.end(await readFile(full))
      } catch {
        res.writeHead(404).end('not found')
      }
    })
if (server) await new Promise((r) => server.listen(PORT, r))

const problems = []
const browser = await chromium.launch()
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, deviceScaleFactor: 2 })
page.on('console', (m) => m.type() === 'error' && problems.push(`console.error: ${m.text()}`))
page.on('pageerror', (e) => problems.push(`pageerror: ${e.message}`))
page.on('requestfailed', (r) => problems.push(`requestfailed: ${r.url()}`))
page.on('response', (r) => r.status() >= 400 && problems.push(`HTTP ${r.status()}: ${r.url()}`))
const shot = async (name) => SHOTS && page.screenshot({ path: `${SHOTS}/${name}.png`, fullPage: true })

try {
  const summary = await (await fetch(`${BASE}/data/latest/summary.json`)).json()
  if (summary.schema_version !== 2) throw new Error(`staged summary is schema_version ${summary.schema_version}, not 2`)

  await page.goto(`${BASE}/#/?tier=all`, { waitUntil: 'networkidle', timeout: 30000 })
  await page.waitForSelector('table.readout', { timeout: 15000 })
  const body = await page.textContent('body')
  for (const bad of ['NaN', 'undefined']) if (body.includes(bad)) problems.push(`page text contains ${bad}`)
  await shot('1-overview')

  // Drill: model -> workload -> gpu -> first deployment.
  for (const sel of ['tr.r0.selrow', 'tr.r1.selrow', 'tr.r2.selrow']) {
    const el = await page.$(sel)
    if (!el) throw new Error(`no row ${sel}`)
    await el.click()
    await page.waitForTimeout(150)
  }
  const topo = await page.$('tr.r3')
  if (!topo) throw new Error('no deployment row after drilling down')
  if (!(await topo.$('.prov-mark'))) problems.push('deployment row has no provenance mark')
  await topo.click()
  await page.waitForSelector('table.pts tbody tr', { timeout: 5000 })
  const rows = await page.$$('table.pts tbody tr')
  const marks = await page.$$('table.pts .prov-mark')
  if (marks.length !== rows.length) problems.push(`points table: ${rows.length} rows but ${marks.length} provenance marks`)
  const head = await page.textContent('table.pts thead')
  if (!head.includes('Measured')) problems.push('points table has no Measured column')
  await shot('2-points')

  // Open a point's provenance tooltip by keyboard focus and read it.
  await page.focus('table.pts td.prov-cell .term')
  const tip = await page.waitForSelector('[role="tooltip"]', { timeout: 3000 })
  const text = await tip.textContent()
  for (const want of ['vLLM build', 'Settings given to BLIS']) if (!text.includes(want)) problems.push(`tooltip lacks "${want}"`)
  if (!/commits (before|after)|at v/.test(text)) problems.push('tooltip states no distance from VLLM_REF')
  await shot('3-provenance-tooltip')
  await page.keyboard.press('Escape')

  // Not-scored points never render.
  const html = await page.content()
  const leaked = (summary.not_scored || []).filter((n) => html.includes(n.point_id))
  if (leaked.length) problems.push(`${leaked.length} not-scored point ids appear in the DOM`)
} catch (e) {
  problems.push(`smoke: ${e.message}`)
}

await browser.close()
if (server) server.close()
if (problems.length) {
  console.error('V2 BROWSER SMOKE FAILED:')
  for (const p of problems) console.error(`  - ${p}`)
  process.exit(1)
}
console.log('v2 browser smoke OK: zero console errors, provenance on every point, not-scored points absent')
