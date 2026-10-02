import { useEffect, useState } from 'react'
import { api } from '../lib/api'
import { errorMessage } from './toast'
import { Badge, Markdown } from './ui'

interface Translation {
  title: string; content: string; original_title: string; original_content: string
  model: string; warnings: string[]; cached: boolean; origin: string
}

const titleRequests = new Map<string, Promise<Translation>>()
function requestTitle(path: string) {
  const pending = titleRequests.get(path)
  if (pending) return pending
  const request = api.get<Translation | null>(path).then((cached) => cached ?? api.post<Translation>(path))
  titleRequests.set(path, request)
  void request.finally(() => titleRequests.delete(path)).catch(() => undefined)
  return request
}

export function useTranslatedTitle(refType: string, refId: string, enabled = true, sourceTitle = '') {
  const path = `/api/translations/${refType}/${refId}?scope=title`
  const [data, setData] = useState<Translation | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [tick, setTick] = useState(0)
  useEffect(() => {
    let alive = true
    setData(null); setError(null)
    if (enabled) requestTitle(path).then((value) => { if (alive) setData(value) }).catch((e) => { if (alive) setError(errorMessage(e)) })
    return () => { alive = false }
  }, [path, enabled, sourceTitle, tick])
  return { data, error, retry: () => setTick((value) => value + 1) }
}

export function looksEnglish(text: string): boolean {
  const latin = (text.match(/[a-z]/gi) ?? []).length
  const chinese = (text.match(/[\u3400-\u9fff]/g) ?? []).length
  return latin > 12 && latin > chinese * 2
}

export function TranslationPanel({ refType, refId, originalContent, onTitle }: {
  refType: 'signal' | 'material' | 'brief_item'; refId: string; originalContent: string
  onTitle?: (title: string | null) => void
}) {
  const path = `/api/translations/${refType}/${refId}?scope=full`
  const title = useTranslatedTitle(refType, refId)
  const [result, setResult] = useState<Translation | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [view, setView] = useState<'zh' | 'original'>('zh')
  const translation = result
  const shownTitle = view === 'zh' ? (translation?.title ?? title.data?.title ?? null) : null
  useEffect(() => { onTitle?.(shownTitle) }, [shownTitle, onTitle])

  async function translate() {
    setBusy(true); setError(null)
    try { setResult(await api.post<Translation>(path)); setView('zh') }
    catch (e) { setError(errorMessage(e)) }
    finally { setBusy(false) }
  }
  return (
    <div className="translation-panel">
      <div className="translation-toolbar">
        {translation ? (
          <>
            <div className="tabs">
              <button className={view === 'zh' ? 'active' : ''} onClick={() => setView('zh')}>中文译文</button>
              <button className={view === 'original' ? 'active' : ''} onClick={() => setView('original')}>英文原文</button>
            </div>
            <span className="tiny muted">AI 翻译 · {translation.model}</span>
          </>
        ) : <button className={`btn sm ${busy ? 'loading' : ''}`} disabled={busy} onClick={translate}>{busy ? '全文翻译中…' : '翻译全文'}</button>}
        {!translation && <span className="tiny muted">仅自动翻译标题，正文按需翻译</span>}
      </div>
      {error && <div className="notice warn small" role="alert">{error}</div>}
      {title.error && !translation && <div className="notice warn small" role="alert">标题翻译失败：{title.error} <button className="btn sm" onClick={title.retry}>重试标题</button></div>}
      {shownTitle && <h3 className="translation-title">{shownTitle}</h3>}
      {translation && view === 'zh' && <>
        {translation.origin === 'mock' && <Badge tone="warn" small>原文为演示素材</Badge>}
        {translation.warnings.map((warning) => <div className="notice warn small" key={warning}>{warning}</div>)}
      </>}
      <div className="translation-body">
        <Markdown text={translation ? (view === 'zh' ? translation.content : translation.original_content) : originalContent} />
      </div>
    </div>
  )
}
