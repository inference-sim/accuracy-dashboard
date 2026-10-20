// Stage the data the build/dev server serves into web/public/data.
//
// Production builds must serve the REAL committed data (repo-root data/: index + latest + ALL
// snapshots) so the run-picker and A/B compare work on the live site. A bare local build/dev with
// no committed data falls back to the single-run test fixture.
//
// The Pages workflow stages data/ explicitly before build (source of truth); this hook just makes a
// plain `npm run build` / `npm run dev` at the repo do the right thing too.
import { existsSync, rmSync, mkdirSync, copyFileSync, cpSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const webDir = join(dirname(fileURLToPath(import.meta.url)), '..')
const repoData = join(webDir, '..', 'data') // repo-root data/
const pub = join(webDir, 'public', 'data')
const fixture = join(webDir, 'testdata', 'render-fixture.summary.json')

// If a caller already staged public/data deliberately (e.g. the CI evaluate job stages just the
// run it produced, or the Pages workflow stages the full committed data/), DON'T clobber it.
if (existsSync(join(pub, 'latest', 'summary.json'))) {
  console.log('[stage-data] public/data already staged — leaving it as-is')
  process.exit(0)
}

const hasRealData = existsSync(join(repoData, 'index.json')) && existsSync(join(repoData, 'latest', 'summary.json'))

rmSync(pub, { recursive: true, force: true })
mkdirSync(join(pub, 'latest'), { recursive: true })

if (hasRealData) {
  copyFileSync(join(repoData, 'index.json'), join(pub, 'index.json'))
  cpSync(join(repoData, 'latest'), join(pub, 'latest'), { recursive: true })
  if (existsSync(join(repoData, 'snapshots'))) cpSync(join(repoData, 'snapshots'), join(pub, 'snapshots'), { recursive: true })
  console.log('[stage-data] staged committed data/ (index + latest + snapshots) — production data')
} else {
  copyFileSync(fixture, join(pub, 'latest', 'summary.json'))
  console.log('[stage-data] no committed data/ — staged the single-run test fixture (local fallback)')
}
