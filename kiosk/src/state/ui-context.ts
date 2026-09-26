import { createContext, useContext } from 'react'

export interface ConfirmRequest {
  title: string
  /** The mono job signature shown under the question, e.g.
   *  control_home_device(target="front door", action="unlock"). */
  sig: string
  yesLabel: string
  onConfirm: () => void
}

export interface UiContextValue {
  toast: (text: string) => void
  confirm: (request: ConfirmRequest) => void
}

export const UiContext = createContext<UiContextValue | null>(null)

export function useUi(): UiContextValue {
  const value = useContext(UiContext)
  if (!value) throw new Error('useUi must be used inside <UiProvider>')
  return value
}
