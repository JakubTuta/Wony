import { useEffect, useRef, useState } from 'react'
import KeyboardReact from 'react-simple-keyboard'

/* The library's own stylesheet is deliberately not imported — app.css restyles
   .hg-button from scratch so the keys belong to the same design as the tiles. */

const LETTERS = [
  'q w e r t y u i o p',
  'a s d f g h j k l',
  '{shift} z x c v b n m {bksp}',
  '{alt} {space} {enter}',
]

const LETTERS_SHIFT = [
  'Q W E R T Y U I O P',
  'A S D F G H J K L',
  '{shift} Z X C V B N M {bksp}',
  '{alt} {space} {enter}',
]

const SYMBOLS = [
  '1 2 3 4 5 6 7 8 9 0',
  "- / : ; ( ) $ & @ \"",
  '{default} . , ? ! \' {bksp}',
  '{default} {space} {enter}',
]

// Typing Polish on a QWERTY layout without these means giving up on the
// language entirely; they are one extra row, not a second keyboard.
const POLISH_ROW = 'ą ć ę ł ń ó ś ź ż'
const POLISH_ROW_SHIFT = 'Ą Ć Ę Ł Ń Ó Ś Ź Ż'

function layoutsFor(language: string) {
  const polish = language.toLowerCase().startsWith('pl')
  return {
    default: polish ? [POLISH_ROW, ...LETTERS] : LETTERS,
    shift: polish ? [POLISH_ROW_SHIFT, ...LETTERS_SHIFT] : LETTERS_SHIFT,
    alt: SYMBOLS,
  }
}

const DISPLAY = {
  '{bksp}': '⌫',
  '{enter}': 'Send',
  '{shift}': '⇧',
  '{space}': ' ',
  '{alt}': '?123',
  '{default}': 'ABC',
}

export function Keyboard({
  value,
  language,
  onChange,
  onSubmit,
}: {
  value: string
  language: string
  onChange: (value: string) => void
  onSubmit: () => void
}) {
  const [layoutName, setLayoutName] = useState<'default' | 'shift' | 'alt'>('default')
  const keyboard = useRef<{ setInput: (v: string) => void } | null>(null)

  // The parent owns the value (it clears it on send). Push those changes down;
  // the library keeps its own copy and would otherwise drift.
  useEffect(() => {
    keyboard.current?.setInput(value)
  }, [value])

  const onKeyPress = (button: string) => {
    if (button === '{shift}') {
      setLayoutName((current) => (current === 'shift' ? 'default' : 'shift'))
      return
    }
    if (button === '{alt}') {
      setLayoutName('alt')
      return
    }
    if (button === '{default}') {
      setLayoutName('default')
      return
    }
    if (button === '{enter}') {
      onSubmit()
      return
    }
    // One capital, then back to lowercase — the phone convention, and the one
    // that stops every second word starting with a stray capital.
    if (layoutName === 'shift') setLayoutName('default')
  }

  return (
    <div className="px-2 pb-2 pt-2 bg-surface border-t border-line">
      <KeyboardReact
        keyboardRef={(r: { setInput: (v: string) => void }) => (keyboard.current = r)}
        layout={layoutsFor(language)}
        layoutName={layoutName}
        display={DISPLAY}
        mergeDisplay
        onChange={onChange}
        onKeyPress={onKeyPress}
        preventMouseDownDefault
      />
    </div>
  )
}
