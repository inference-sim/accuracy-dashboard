/**
 * An accessible term-explanation tooltip. The visible label gets a dotted underline; hovering OR
 * keyboard-focusing it shows a small popover with the definition (Esc or blur/mouseleave hides it).
 *
 * Accessibility (why not a bare `title=`): `title` is invisible to keyboard users and touch, and
 * screen readers treat it inconsistently. Here the trigger is focusable (tabIndex 0), the popover is
 * `role="tooltip"`, and `aria-describedby` links them so the definition is announced on focus.
 *
 * Renders an inline <span> (never a <button>), so it is SAFE to place inside another interactive
 * element's label without nesting interactive controls — but note it is still focusable, so it must
 * NOT be nested inside a real <button> (that would be a focusable-in-focusable a11y error); for the
 * sortable mape/shape headers the caller keeps the Term OUTSIDE the sort button.
 */
import { useId, useRef, useState } from 'react'
import { GLOSSARY } from '../glossary'

interface Props {
  /** key into GLOSSARY; the visible text is GLOSSARY[name].label unless `children` overrides it. */
  name: keyof typeof GLOSSARY
  children?: React.ReactNode
}

export function Term({ name, children }: Props) {
  const entry = GLOSSARY[name]
  const [open, setOpen] = useState(false)
  // Esc closes the popover while the trigger keeps focus; without this latch onFocus would never
  // fire again (focus never left), stranding keyboard users with no way to reopen (jgchn review).
  // The latch suppresses the focus-reopen until it's cleared — on blur, or on the next keydown so
  // the keyboard can reopen in place.
  const escDismissed = useRef(false)
  const id = useId()
  if (!entry) return <>{children}</>

  const hide = () => setOpen(false)

  return (
    <span className="term-wrap">
      <span
        className="term"
        tabIndex={0}
        aria-describedby={open ? id : undefined}
        onMouseEnter={() => setOpen(true)}
        onMouseLeave={hide}
        onFocus={() => {
          if (!escDismissed.current) setOpen(true)
        }}
        onBlur={() => {
          escDismissed.current = false
          hide()
        }}
        onKeyDown={(e) => {
          if (e.key === 'Escape') {
            escDismissed.current = true
            hide()
          } else {
            // any other key re-arms focus-based showing and reopens in place
            escDismissed.current = false
            setOpen(true)
          }
        }}
      >
        {children ?? entry.label}
      </span>
      {/* Rendered only when open so SSR/markup stays clean; role=tooltip + id for aria-describedby. */}
      {open && (
        <span role="tooltip" id={id} className="term-pop">
          {entry.definition}
        </span>
      )}
    </span>
  )
}
