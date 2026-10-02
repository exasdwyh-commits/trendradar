import { createContext, useCallback, useContext, useMemo, useRef, useState } from 'react'
import { Icon } from './icons'

type Tone = 'info' | 'good' | 'warn' | 'bad'
interface Toast { id: number; message: string; tone: Tone; leaving?: boolean }
interface ToastApi { toast: (message: string, tone?: Tone) => void }

const ToastContext = createContext<ToastApi>({ toast: () => undefined })

const TONE_ICON: Record<Tone, string> = { info: 'spark', good: 'check', warn: 'eye', bad: 'x' }

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [items, setItems] = useState<Toast[]>([])
  const seq = useRef(0)

  const dismiss = useCallback((id: number) => {
    setItems((list) => list.map((t) => (t.id === id ? { ...t, leaving: true } : t)))
    setTimeout(() => setItems((list) => list.filter((t) => t.id !== id)), 220)
  }, [])

  const toast = useCallback((message: string, tone: Tone = 'info') => {
    const id = ++seq.current
    setItems((list) => [...list.slice(-3), { id, message, tone }])
    setTimeout(() => dismiss(id), tone === 'bad' ? 6000 : 2800)
  }, [dismiss])

  const api = useMemo(() => ({ toast }), [toast])
  return (
    <ToastContext.Provider value={api}>
      {children}
      <div className="toaster" aria-live="polite">
        {items.map((t) => (
          <div key={t.id} className={`toast ${t.tone} ${t.leaving ? 'leaving' : ''}`} onClick={() => dismiss(t.id)}>
            <Icon name={TONE_ICON[t.tone]} size={15} />
            <span>{t.message}</span>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  )
}

export function useToast() {
  return useContext(ToastContext)
}

export function errorMessage(e: unknown): string {
  return e instanceof Error ? e.message : String(e)
}
