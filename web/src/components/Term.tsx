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
 *
 * The popover is position:fixed, placed from the trigger's on-screen box when it opens, so no
 * ancestor's overflow (the scrolling table wrapper) can clip it (PR #26 review). It flips above the
 * trigger when there's no room below and is kept inside the window horizontally.
 */
import { useId, useLayoutEffect, useRef, useState } from 'react'
import { GLOSSARY } from '../glossary'

interface Props {
  /** key into GLOSSARY; the visible text is GLOSSARY[name].label unless `children` overrides it. */
  name?: keyof typeof GLOSSARY
  /** Popover content given directly (generalised for the provenance tooltip, #30); with `name`
   *  absent, `children` is the visible trigger and this is the body. */
  content?: React.ReactNode
  /** an extra class on the popover, e.g. a wider one for structured content */
  popClass?: string
  /** accessible label for a trigger that is only a symbol */
  ariaLabel?: string
  children?: React.ReactNode
}

export function Term({ name, content, popClass, ariaLabel, children }: Props) {
  const entry = name ? GLOSSARY[name] : content != null ? { label: '', definition: content } : undefined
  const [open, setOpen] = useState(false)
  // Esc closes the popover while the trigger keeps focus; without this latch onFocus would never
  // fire again (focus never left), stranding keyboard users with no way to reopen (jgchn review).
  // The latch suppresses the focus-reopen until it's cleared — on blur, or on the next keydown so
  // the keyboard can reopen in place.
  const escDismissed = useRef(false)
  const id = useId()
  const trigger = useRef<HTMLSpanElement>(null)
  const pop = useRef<HTMLSpanElement>(null)
  const [pos, setPos] = useState<{ left: number; top: number } | null>(null)

  // Place the popover once it has rendered (so its own size is known), then on scroll/resize.
  useLayoutEffect(() => {
    if (!open) {
      setPos(null)
      return
    }
    const place = () => {
      const t = trigger.current?.getBoundingClientRect()
      const p = pop.current?.getBoundingClientRect()
      if (!t || !p) return
      const gap = 6
      const margin = 8
      const below = t.bottom + gap
      const top = below + p.height > window.innerHeight - margin ? Math.max(margin, t.top - gap - p.height) : below
      const left = Math.min(Math.max(margin, t.left), window.innerWidth - margin - p.width)
      setPos({ left, top })
    }
    place()
    window.addEventListener('scroll', place, true)
    window.addEventListener('resize', place)
    return () => {
      window.removeEventListener('scroll', place, true)
      window.removeEventListener('resize', place)
    }
  }, [open])

  if (!entry) return <>{children}</>

  const hide = () => setOpen(false)

  return (
    <span className="term-wrap">
      <span
        ref={trigger}
        className="term"
        tabIndex={0}
        aria-label={ariaLabel}
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
        <span
          role="tooltip"
          id={id}
          ref={pop}
          className={popClass ? `term-pop ${popClass}` : 'term-pop'}
          // hidden until measured, so it never flashes at the wrong spot
          style={pos ? { left: pos.left, top: pos.top } : { visibility: 'hidden' }}
        >
          {entry.definition}
        </span>
      )}
    </span>
  )
}
