import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { App } from './App'
import { loadIndex, RunLoader, type RunIndex } from './load'
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
let loader = new RunLoader(null) // caches per run so a revisited run keeps one object identity
let currentKey: string | null = null // the (A|B) pair currently loaded, to avoid redundant reloads

function render(summary: Summary | null, summaryB: Summary | null, loadError: string | null) {
  reactRoot.render(
    <StrictMode>
      <App summary={summary} summaryB={summaryB} loadError={loadError} index={index} />
    </StrictMode>,
  )
}

async function loadForHash() {
  const route = parseRoute(window.location.hash)
  // The pair key covers both A and B so the dedup guard reloads when EITHER slot changes (incl.
  // entering/leaving compare mode). The newest snapshot id and "latest" share a key, so toggling
  // Compare on the newest run doesn't reload the Overview. Non-run params (tier/sel/filter) don't
  // change the key and are handled in-App.
  const key = `${loader.keyFor(route.run)}||${route.runB ? loader.keyFor(route.runB) : '-'}`
  if (key === currentKey) return
  currentKey = key
  try {
    // A-vs-B compare mode loads BOTH snapshots concurrently; single-run loads just A.
    const [a, b] = await Promise.all([loader.load(route.run), route.runB ? loader.load(route.runB) : Promise.resolve(null)])
    render(a, b, null)
  } catch (e) {
    render(null, null, (e as Error).message)
  }
}

render(null, null, null) // loading state

// Load the index first (so the picker is populated), then the current run; reload on run change.
loadIndex().then((idx) => {
  index = idx
  loader = new RunLoader(idx)
  loadForHash()
})
window.addEventListener('hashchange', () => {
  // Only reload when the RUN changes; other route params (tier/filter/sel) are handled in-App.
  loadForHash()
})
