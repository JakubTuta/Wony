import { useCallback, useMemo, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { ConfirmSheet } from '../components/ConfirmSheet'
import { Toast } from '../components/Toast'
import { UiContext } from './ui-context'
import type { ConfirmRequest, UiContextValue } from './ui-context'

/** Toast and the confirm sheet live above every screen, so any tile — Home,
 *  Rooms, Music, Macros — can ask for either without threading callbacks
 *  through five layers of props. Rendered inside Frame's 1280×800 box so the
 *  overlays sit over the panel, not the whole browser window. */
export function UiProvider({ children }: { children: ReactNode }) {
  const [toastText, setToastText] = useState<string | null>(null)
  const [confirmRequest, setConfirmRequest] = useState<ConfirmRequest | null>(null)
  const toastTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  const toast = useCallback((text: string) => {
    if (toastTimer.current) clearTimeout(toastTimer.current)
    setToastText(text)
    toastTimer.current = setTimeout(() => setToastText(null), 2600)
  }, [])

  const confirm = useCallback((request: ConfirmRequest) => setConfirmRequest(request), [])

  const value = useMemo<UiContextValue>(() => ({ toast, confirm }), [toast, confirm])

  return (
    <UiContext.Provider value={value}>
      {children}
      {toastText && <Toast text={toastText} />}
      {confirmRequest && (
        <ConfirmSheet request={confirmRequest} onCancel={() => setConfirmRequest(null)} />
      )}
    </UiContext.Provider>
  )
}
