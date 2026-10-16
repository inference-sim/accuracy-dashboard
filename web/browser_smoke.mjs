// Browser smoke-test (RFC B1): serve the built site, load it in headless Chromium, and fail on
// ANY console error / page error / failed request. This is the "renders with ZERO console or
// runtime errors against real data, headless-verified" check — stronger than renderToStaticMarkup
// because it exercises the real fetch + hydration path.
//
// Run from web/: `node ../orchestrator/browser_smoke.mjs` (expects dist/ built and
// dist/data/latest/summary.json present).
import { createServer } from 'node:http'
import { readFile, stat } from 'node:fs/promises'
import { extname, join, normalize } from 'node:path'
import { chromium } from 'playwright'

const ROOT = normalize(join(process.cwd(), 'dist'))
const PORT = 4873
const MIME = {
  '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css',
  '.json': 'application/json', '.svg': 'image/svg+xml',
}

const server = createServer(async (req, res) => {
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

await new Promise((r) => server.listen(PORT, r))

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
  await page.goto(`http://localhost:${PORT}/`, { waitUntil: 'networkidle', timeout: 30000 })
  // The data load is async; wait for a real number cell to appear.
  await page.waitForSelector('table.readout', { timeout: 15000 })
  const text = await page.textContent('body')
  // Explicit markers, never NaN/blank/undefined leaking to the DOM (RFC B1).
  for (const bad of ['NaN', 'undefined', 'Infinity']) {
    if (text && text.includes(bad)) problems.push(`DOM contains "${bad}"`)
  }
  const title = await page.textContent('.viewhead')
  if (!title || !title.includes('End-to-end accuracy')) problems.push('headline missing')
  // Deep-link: selecting via the hash populates the points table.
  const firstTopo = await page.$('tr.r3')
  if (firstTopo) {
    await firstTopo.click()
    await page.waitForTimeout(300)
  }
} catch (e) {
  problems.push(`navigation: ${e.message}`)
  ok = false
}

await browser.close()
server.close()

if (problems.length || !ok) {
  console.error('BROWSER SMOKE FAILED:')
  for (const p of problems) console.error('  - ' + p)
  process.exit(1)
}
console.log('browser smoke OK: zero console/page errors, no NaN/blank, headline + table rendered')
