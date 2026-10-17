// Browser smoke-test (RFC B1): load the site in headless Chromium and fail on ANY console error
// / page error / failed request. Stronger than renderToStaticMarkup because it exercises the real
// fetch + client reconciliation path — which is the ONLY place React surfaces warnings like
// duplicate keys (SSR does not emit them), the class of bug that repeat-concurrency points caused.
//
// Two modes:
//   - default: serve ./dist (expects `vite build` + dist/data/latest/summary.json). Production
//     React strips warnings, so this catches runtime throws / failed fetches / NaN, not warnings.
//   - SMOKE_URL=<url>: target an already-running server (e.g. `npm run dev` at :5173). Against the
//     DEV server React is unminified and emits key/validation warnings — run this in CI too.
import { createServer } from 'node:http'
import { readFile, stat } from 'node:fs/promises'
import { extname, join, normalize } from 'node:path'
import { chromium } from 'playwright'

const EXTERNAL = process.env.SMOKE_URL || ''
const ROOT = normalize(join(process.cwd(), 'dist'))
const PORT = 4873
const BASE = EXTERNAL || `http://localhost:${PORT}`
const MIME = {
  '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css',
  '.json': 'application/json', '.svg': 'image/svg+xml',
}

const server = EXTERNAL
  ? null
  : createServer(async (req, res) => {
      try {
        let p = decodeURIComponent((req.url || '/').split('?')[0])
        if (p === '/') p = '/index.html'
        const full = normalize(join(ROOT, p))
        if (!full.startsWith(ROOT)) {
          res.writeHead(403).end('forbidden')
          return
        }
        await stat(full)
        const body = await readFile(full)
        res.writeHead(200, { 'content-type': MIME[extname(full)] || 'application/octet-stream' })
        res.end(body)
      } catch {
        res.writeHead(404).end('not found')
      }
    })

if (server) await new Promise((r) => server.listen(PORT, r))

const browser = await chromium.launch()
const page = await browser.newPage()
const problems = []
page.on('console', (m) => {
  if (m.type() === 'error') problems.push(`console.error: ${m.text()}`)
})
page.on('pageerror', (e) => problems.push(`pageerror: ${e.message}`))
page.on('requestfailed', (r) => problems.push(`requestfailed: ${r.url()} ${r.failure()?.errorText}`))

let ok = true
try {
  await page.goto(`${BASE}/#/`, { waitUntil: 'networkidle', timeout: 30000 })
  // The data load is async; wait for a real number cell to appear.
  await page.waitForSelector('table.readout', { timeout: 15000 })
  // Drill model → workload → GPU → topology so the POINTS table renders — the repeat-concurrency
  // rows that triggered the duplicate-key warning live there. In dev mode React emits it here.
  for (const sel of ['tr.r0.selrow', 'tr.r1.selrow', 'tr.r2.selrow', 'tr.r3']) {
    const el = await page.$(sel)
    if (el) {
      await el.click()
      await page.waitForTimeout(300)
    }
  }
  await page.waitForTimeout(300)
  const text = await page.textContent('body')
  // Explicit markers, never NaN/blank/undefined leaking to the DOM (RFC B1).
  for (const bad of ['NaN', 'undefined', 'Infinity']) {
    if (text && text.includes(bad)) problems.push(`DOM contains "${bad}"`)
  }
  const title = await page.textContent('.viewhead')
  if (!title || !title.includes('End-to-end accuracy')) problems.push('headline missing')
} catch (e) {
  problems.push(`navigation: ${e.message}`)
  ok = false
}

await browser.close()
if (server) server.close()

if (problems.length || !ok) {
  console.error('BROWSER SMOKE FAILED:')
  for (const p of problems) console.error('  - ' + p)
  process.exit(1)
}
console.log('browser smoke OK: zero console/page errors, no NaN/blank, headline + table rendered')
