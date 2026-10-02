import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from './api'

export function useFetch<T>(path: string | null, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<unknown>(null)
  const [loading, setLoading] = useState<boolean>(!!path)
  const [tick, setTick] = useState(0)
  const previousPath = useRef(path)
  const reload = useCallback(() => setTick((t) => t + 1), [])
  useEffect(() => {
    // Keep current data during a refresh, but never show it for another resource.
    if (path !== previousPath.current || !path) setData(null)
    previousPath.current = path
    setError(null)
    if (!path) {
      setLoading(false)
      return
    }
    let alive = true
    const controller = new AbortController()
    setLoading(true)
    api.get<T>(path, { signal: controller.signal }).then((d) => { if (alive) { setData(d); setError(null) } }).catch((e) => { if (alive) setError(e) }).finally(() => { if (alive) setLoading(false) })
    return () => { alive = false; controller.abort() }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path, tick, ...deps])
  return { data, error, loading, reload }
}

export function useTheme() {
  const [theme, setTheme] = useState<string>(() => localStorage.getItem('theme') || (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'))
  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme)
    localStorage.setItem('theme', theme)
  }, [theme])
  return { theme, toggle: () => setTheme(theme === 'dark' ? 'light' : 'dark') }
}
