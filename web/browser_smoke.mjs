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
// data/index.json is OPTIONAL by design: loadIndex() tolerates its absence (a site published
// before the run-picker existed) and degrades to latest-only. A 404 on it is expected, not a
// defect. The browser's generic "Failed to load resource: 404" console message does NOT carry
// the URL, so we can't filter by text — instead we track which URLs actually 4xx'd via the
// `response` event, and treat a bare 404 console error as noise IFF the only 4xx responses were
// the optional index. Any other 4xx (or any non-404 console error) is fatal.
const bad4xx = [] // non-index URLs that returned >=400
const consoleErrors = [] // collected, judged at the end (avoids a console/response ordering race)
const isOptionalIndex = (u) => /index\.json(\?|$)/.test(u)
page.on('response', (r) => {
  if (r.status() >= 400 && !isOptionalIndex(r.url())) bad4xx.push(`${r.status()} ${r.url()}`)
})
page.on('console', (m) => {
  if (m.type() === 'error') consoleErrors.push(m.text())
})
page.on('pageerror', (e) => problems.push(`pageerror: ${e.message}`))
page.on('requestfailed', (r) => {
  if (!isOptionalIndex(r.url())) problems.push(`requestfailed: ${r.url()} ${r.failure()?.errorText}`)
})

let ok = true
try {
  await page.goto(`${BASE}/#/`, { waitUntil: 'networkidle', timeout: 30000 })
  // The data load is async; wait for a real number cell to appear.
  await page.waitForSelector('table.readout', { timeout: 15000 })
  // Drill model → workload → GPU → topology so the POINTS table renders. FAIL LOUD if a level is
  // missing (PR #3 review T-c): the old `if (el)` silently skipped, so a broken table that renders
  // no rows would pass the smoke. Each level must exist for the real snapshot.
  for (const sel of ['tr.r0.selrow', 'tr.r1.selrow', 'tr.r2.selrow', 'tr.r3']) {
    const el = await page.$(sel)
    if (!el) {
      problems.push(`drill-down: expected a row matching "${sel}" but found none (table is empty or broken)`)
      break
    }
    await el.click()
    await page.waitForTimeout(300)
  }
  await page.waitForTimeout(300)
  // After drilling to a topology, the points table must actually render rows (not the empty prompt).
  const ptRows = await page.$$('table.pts tbody tr')
  if (ptRows.length === 0) problems.push('drill-down: points table rendered zero rows after selecting a topology')

  // Exercise the styled dropdown (replaces native <select>): open it, assert the popup listbox
  // appears, pick the last option, confirm it closes. This is the interactive path SSR can't cover.
  const ddTrigger = await page.$('.dd-trigger.vllmsel')
  if (ddTrigger) {
    await ddTrigger.click()
    await page.waitForSelector('.dd-list [role="option"]', { timeout: 3000 })
    const opts = await page.$$('.dd-list .dd-opt')
    if (opts.length < 1) problems.push('dropdown opened with no options')
    await opts[opts.length - 1].click()
    await page.waitForTimeout(150)
    if (await page.$('.dd-list')) problems.push('dropdown did not close after selection')
  } else {
    problems.push('styled vLLM dropdown not found')
  }

  // Exercise a term tooltip (accessible hover/focus popover): focus a term → role=tooltip appears,
  // Esc hides it. Covers the interactive a11y path SSR can't.
  const term = await page.$('.term')
  if (term) {
    await term.focus()
    await page.waitForSelector('[role="tooltip"]', { timeout: 2000 }).catch(() => {})
    if (!(await page.$('[role="tooltip"]'))) problems.push('term tooltip did not appear on focus')
    await page.keyboard.press('Escape')
    await page.waitForTimeout(100)
    if (await page.$('[role="tooltip"]')) problems.push('term tooltip did not hide on Esc')
    // Esc must not strand the keyboard: focus stays on the trigger, so a subsequent keydown has to
    // reopen it in place (jgchn review — the dismiss-latch re-arm path).
    await page.keyboard.press('ArrowDown')
    await page.waitForTimeout(100)
    if (!(await page.$('[role="tooltip"]'))) problems.push('term tooltip did not reopen on keydown after Esc')
  } else {
    problems.push('no .term tooltip trigger found on the page')
  }

  // Exercise the collapsible sidebar: collapse, assert the layout + rail shrink, then expand back.
  const collapseBtn = await page.$('.rail .railtoggle')
  if (collapseBtn) {
    await collapseBtn.click()
    await page.waitForSelector('.layout.collapsed', { timeout: 3000 })
    if (!(await page.$('.rail.railmini'))) problems.push('rail did not switch to mini on collapse')
    await page.click('.rail.railmini .railtoggle')
    await page.waitForTimeout(150)
    if (await page.$('.layout.collapsed')) problems.push('sidebar did not expand back')
  } else {
    problems.push('sidebar collapse toggle not found')
  }

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

// Judge console errors now that all responses have settled. A bare "Failed to load resource: 404"
// with NO non-index 4xx is the optional data/index.json — expected, ignore. Everything else fatal.
for (const t of consoleErrors) {
  const isBare404 = /Failed to load resource/.test(t) && /404|Not Found/.test(t)
  if (isBare404 && bad4xx.length === 0) continue
  problems.push(`console.error: ${t}`)
}

await browser.close()
if (server) server.close()

if (problems.length || !ok) {
  console.error('BROWSER SMOKE FAILED:')
  for (const p of problems) console.error('  - ' + p)
  process.exit(1)
}
console.log('browser smoke OK: zero console/page errors, no NaN/blank, headline + table rendered')
