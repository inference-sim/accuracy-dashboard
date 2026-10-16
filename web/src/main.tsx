import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { App } from './App'
import { loadSummary } from './load'
import type { Summary } from './types'
import './styles.css'

const root = document.getElementById('root')
if (!root) throw new Error('#root is missing from index.html')

const reactRoot = createRoot(root)

// Render a loading state first, then the data once it arrives. A load/validation failure is
// shown as a clear message, never a blank page (RFC B1/C3).
reactRoot.render(
  <StrictMode>
    <App summary={null} loadError={null} />
  </StrictMode>,
)

loadSummary()
  .then((summary: Summary) => {
    reactRoot.render(
      <StrictMode>
        <App summary={summary} loadError={null} />
      </StrictMode>,
    )
  })
  .catch((e: Error) => {
    reactRoot.render(
      <StrictMode>
        <App summary={null} loadError={e.message} />
      </StrictMode>,
    )
  })
