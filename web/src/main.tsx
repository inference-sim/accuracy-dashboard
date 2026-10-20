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
let currentKey: string | null = null // the (A|B) pair currently loaded, to avoid redundant reloads

function render(summary: Summary | null, summaryB: Summary | null, loadError: string | null) {
  reactRoot.render(
    <StrictMode>
      <App summary={summary} summaryB={summaryB} loadError={loadError} index={index} />
    </StrictMode>,
  )
}

/** Resolve a run (null = latest) to a loader promise. A named run must be in the index. */
function loadRun(want: string | null): Promise<Summary> {
  if (!want) return loadSummary() // latest
  const ref = index ? index.runs.find((r) => r.snapshot_id === want) : null
  return ref ? loadSummaryAt(ref.path) : missing(want)
}

/** A stable cache key for a resolved run (null → 'latest', unknown id → 'missing:<id>'). */
function keyFor(want: string | null): string {
  if (!want) return 'latest'
  return index && index.runs.some((r) => r.snapshot_id === want) ? want : `missing:${want}`
}

async function loadForHash() {
  const route = parseRoute(window.location.hash)
  // The pair key covers both A and B so the dedup guard reloads when EITHER slot changes (incl.
  // entering/leaving compare mode). Non-run param changes (tier/sel/filter) don't change the key.
  const key = `${keyFor(route.run)}||${route.runB ? keyFor(route.runB) : '-'}`
  if (key === currentKey) return
  currentKey = key
  try {
    // A-vs-B compare mode loads BOTH snapshots concurrently; single-run loads just A.
    const [a, b] = await Promise.all([loadRun(route.run), route.runB ? loadRun(route.runB) : Promise.resolve(null)])
    render(a, b, null)
  } catch (e) {
    render(null, null, (e as Error).message)
  }
}

function missing(id: string): Promise<Summary> {
  return Promise.reject(new Error(`run "${id}" is not in the published index (it may have aged out of the 30-day window)`))
}

render(null, null, null) // loading state

// Load the index first (so the picker is populated), then the current run; reload on run change.
loadIndex().then((idx) => {
  index = idx
  loadForHash()
})
window.addEventListener('hashchange', () => {
  // Only reload when the RUN changes; other route params (tier/filter/sel) are handled in-App.
  loadForHash()
})
