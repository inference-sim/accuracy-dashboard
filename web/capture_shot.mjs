// One-off UI screenshot for the PR embed. Not part of CI. Run against the dev server:
//   npm run dev &  ; OUT=../docs/screenshots/overview-v0.1.0-rendered.png node capture_shot.mjs
import { chromium } from 'playwright'

const URL = process.env.SHOT_URL || 'http://localhost:5173'
const OUT = process.env.OUT || '/tmp/overview.png'

const browser = await chromium.launch()
const page = await browser.newPage({ viewport: { width: 1440, height: 1100 }, deviceScaleFactor: 2 })
await page.goto(`${URL}/#/`, { waitUntil: 'networkidle', timeout: 30000 })
await page.waitForSelector('table.readout', { timeout: 15000 })
// Drill into a topology so the points table (with sign-coloured errors) is visible in the shot.
for (const sel of ['tr.r0.selrow', 'tr.r1.selrow', 'tr.r2.selrow', 'tr.r3']) {
  const el = await page.$(sel)
  if (el) {
    await el.click()
    await page.waitForTimeout(250)
  }
}
await page.waitForTimeout(400)
await page.screenshot({ path: OUT, fullPage: true })
await browser.close()
console.log('shot ->', OUT)
