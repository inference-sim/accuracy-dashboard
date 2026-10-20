/**
 * Term tooltip — static/SSR assertions. The popover is state-driven (shows on hover/focus), which a
 * node/SSR render can't exercise; the interactive show/Esc path is covered by browser_smoke.mjs.
 * Here we assert the trigger renders accessibly and every glossary term is wired.
 */
import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { Term } from './components/Term'
import { GLOSSARY } from './glossary'

describe('Term (accessible tooltip trigger)', () => {
  it('renders the label as a focusable term trigger', () => {
    const html = renderToStaticMarkup(<Term name="mape" />)
    expect(html).toContain('class="term"')
    expect(html).toContain('tabindex="0"') // keyboard-focusable (not a bare title=)
    expect(html).toContain('mape') // the visible label
  })

  it('renders custom children (e.g. the ⓘ info marker) instead of the label', () => {
    const html = renderToStaticMarkup(
      <Term name="shape">
        <sup>ⓘ</sup>
      </Term>,
    )
    expect(html).toContain('ⓘ')
  })

  it('an unknown term degrades to just its children (no crash)', () => {
    // @ts-expect-error intentionally passing a non-glossary key
    const html = renderToStaticMarkup(<Term name="nope">x</Term>)
    expect(html).toContain('x')
    expect(html).not.toContain('class="term"')
  })

  it('every glossary entry has a label and a non-trivial definition', () => {
    for (const [key, e] of Object.entries(GLOSSARY)) {
      expect(e.label, key).toBeTruthy()
      expect(e.definition.length, key).toBeGreaterThan(20)
    }
    // all 7 terms from issue #4 are present (5 core metrics + coverage/not-scored + A/B diff)
    for (const k of ['mape', 'shape', 'ttft', 'tpot', 'tier', 'coverage', 'diff']) {
      expect(GLOSSARY, k).toHaveProperty(k)
    }
  })
})
