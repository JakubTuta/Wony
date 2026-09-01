import { useEffect } from 'react'

const EDITABLE = new Set(['INPUT', 'TEXTAREA', 'SELECT'])

/** Start typing on any screen and end up in the chat, with the character kept.
 *
 *  Without this, plugging a keyboard into the Pi and typing on the home screen
 *  does nothing at all: there is no field there to receive it. Text fields
 *  accepting keys is not the same as the device accepting keys.
 *
 *  Ignores anything with a modifier (those are shortcuts, not text) and
 *  anything aimed at a field that is already focused, which is why the chat
 *  screen does not double-handle its own input.
 */
export function useTypeAnywhere(onType: (char: string) => void): void {
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.ctrlKey || event.metaKey || event.altKey) return

      const target = event.target as HTMLElement | null
      if (target && (EDITABLE.has(target.tagName) || target.isContentEditable)) return

      // Exactly one character is the portable test for "this key produces
      // text": it holds for letters, digits, punctuation, space and é alike,
      // and excludes Shift, Enter, F5 and the arrows.
      if (event.key.length !== 1) return

      // Space would scroll the page out from under the screen change.
      event.preventDefault()
      onType(event.key)
    }

    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [onType])
}
