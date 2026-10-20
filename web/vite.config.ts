import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

// The site and its data ship on one GitHub Pages branch (RFC §4.2), so the dashboard
// fetches data/latest/summary.json as a plain same-origin request. `base` is relative so
// the built site works under the project-pages subpath (…/accuracy-dashboard/).
export default defineConfig({
  base: './',
  plugins: [react()],
  // The committed snapshots live in ../data, a sibling of web/, above the Vite root.
  publicDir: 'public',
  server: { fs: { allow: ['..'] } },
  test: {
    globals: true,
    // format.ts and aggregate.ts are pure; renderToStaticMarkup needs no DOM.
    environment: 'node',
    include: ['src/**/*.test.ts', 'src/**/*.test.tsx'],
  },
})
