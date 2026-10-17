import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { App } from './App'
import { loadIndex, loadSummary, loadSummaryAt, type RunIndex } from './load'
import { parseRoute } from './route'
import type { Summary } from './types'
import './styles.css'

const root = document.getElementById('root')
if (!root) throw new Error('#root is missing from index.html')
const reactRoot = createRoot(root)

// The run-picker lets a user view an OLDER nightly run's full results. Which run is viewed lives
// in the URL hash (?run=<snapshot_id>); selecting a run only loads that snapshot — it never
// triggers a new evaluation. The index (data/index.json) lists the retained runs; absent → the
// site just shows the latest with no picker.
let index: RunIndex | null = null
let currentRun: string | null = null // the run_id currently loaded, to avoid redundant reloads

function render(summary: Summary | null, loadError: string | null) {
  reactRoot.render(
    <StrictMode>
      <App summary={summary} loadError={loadError} index={index} />
    </StrictMode>,
  )
}

async function loadForHash() {
  const want = parseRoute(window.location.hash).run
  // A named run resolves to its path via the index; otherwise the latest snapshot.
  const ref = want && index ? index.runs.find((r) => r.snapshot_id === want) : null
  const key = ref ? ref.snapshot_id : want ? `missing:${want}` : 'latest'
  if (key === currentRun) return // already showing it (e.g. a non-run param changed)
  currentRun = key
  try {
    const summary = ref ? await loadSummaryAt(ref.path) : want ? await missing(want) : await loadSummary()
    render(summary, null)
  } catch (e) {
    render(null, (e as Error).message)
  }
}

function missing(id: string): Promise<Summary> {
  return Promise.reject(new Error(`run "${id}" is not in the published index (it may have aged out of the 30-day window)`))
}

render(null, null) // loading state

// Load the index first (so the picker is populated), then the current run; reload on run change.
loadIndex().then((idx) => {
  index = idx
  loadForHash()
})
window.addEventListener('hashchange', () => {
  // Only reload when the RUN changes; other route params (tier/filter/sel) are handled in-App.
  loadForHash()
})
