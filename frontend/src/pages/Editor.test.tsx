// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import Editor from './Editor'
import { api } from '../lib/api'
import { Markdown } from '../components/ui'

const { doc, reload } = vi.hoisted(() => ({
  reload: vi.fn(),
  doc: { id: 'test-doc', title: '测试稿', content_md: '已保存正文', thesis: '', status: 'draft', target_platform: 'wechat', data_mode: 'mock', current_version: 1, materials: [], versions: [], variants: [], publications: [], ai_actions: [] },
}))
vi.mock('../lib/hooks', () => ({ useFetch: (path: string) => ({ data: path?.includes('/documents/') ? doc : { model_available: true }, error: null, reload }) }))

beforeEach(() => {
  const data = new Map<string, string>()
  vi.stubGlobal('localStorage', { getItem: (key: string) => data.get(key) ?? null, setItem: (key: string, value: string) => data.set(key, value), removeItem: (key: string) => data.delete(key) })
  vi.useFakeTimers()
  localStorage.setItem('ui.editor.view', JSON.stringify('edit'))
})
afterEach(() => { cleanup(); vi.useRealTimers(); vi.restoreAllMocks() })
function openEditor() { return render(<MemoryRouter initialEntries={['/studio/test-doc']}><Routes><Route path="/studio/:id" element={<Editor />} /></Routes></MemoryRouter>) }

it('saves new typing even when an older save finishes during typing', async () => {
  let finish!: (value: unknown) => void
  const patch = vi.spyOn(api, 'patch').mockImplementationOnce(() => new Promise((resolve) => { finish = resolve })) .mockResolvedValue(doc)
  openEditor()
  fireEvent.change(document.querySelector('textarea')!, { target: { value: '第一次修改' } })
  await act(async () => { vi.advanceTimersByTime(1500) })
  fireEvent.change(document.querySelector('textarea')!, { target: { value: '最新修改' } })
  await act(async () => { finish(doc) })
  expect(screen.getByText(/未保存/)).toBeTruthy()
  await act(async () => { vi.advanceTimersByTime(1500) })
  expect(patch).toHaveBeenLastCalledWith('/api/documents/test-doc', expect.objectContaining({ content_md: '最新修改' }))
})

it('recovers unsaved text after leaving and reopening the editor', () => {
  const first = openEditor()
  fireEvent.change(document.querySelector('textarea')!, { target: { value: '尚未上传的草稿' } })
  first.unmount()
  openEditor()
  expect((document.querySelector('textarea') as HTMLTextAreaElement).value).toBe('尚未上传的草稿')
})

it('warns before closing with unsaved changes', () => {
  openEditor()
  fireEvent.change(document.querySelector('textarea')!, { target: { value: '尚未保存' } })
  const event = new Event('beforeunload', { cancelable: true })
  window.dispatchEvent(event)
  expect(event.defaultPrevented).toBe(true)
})

it('serializes saves so an older request cannot overwrite newer content', async () => {
  let finish!: (value: unknown) => void
  const patch = vi.spyOn(api, 'patch').mockImplementationOnce(() => new Promise((resolve) => { finish = resolve })).mockResolvedValue(doc)
  openEditor()
  fireEvent.change(document.querySelector('textarea')!, { target: { value: '较早的正文' } })
  await act(async () => { vi.advanceTimersByTime(1500) })
  fireEvent.change(document.querySelector('textarea')!, { target: { value: '较新的正文' } })
  await act(async () => { vi.advanceTimersByTime(1500) })
  expect(patch).toHaveBeenCalledTimes(1)
  await act(async () => { finish(doc) })
  expect(patch).toHaveBeenCalledTimes(2)
  expect(patch).toHaveBeenLastCalledWith('/api/documents/test-doc', expect.objectContaining({ content_md: '较新的正文' }))
})

it('keeps a recoverable draft when the server rejects a save', async () => {
  vi.spyOn(api, 'patch').mockRejectedValue(new Error('offline'))
  const first = openEditor()
  fireEvent.change(document.querySelector('textarea')!, { target: { value: '离线内容' } })
  await act(async () => { vi.advanceTimersByTime(1500) })
  expect(screen.getByText(/未保存/)).toBeTruthy()
  first.unmount()
  openEditor()
  expect((document.querySelector('textarea') as HTMLTextAreaElement).value).toBe('离线内容')
})

it('saves the current text before asking the writing model', async () => {
  const order: string[] = []
  vi.spyOn(api, 'patch').mockImplementation(async () => { order.push('save'); return doc })
  vi.spyOn(api, 'post').mockImplementation(async () => { order.push('model'); throw new Error('test response') })
  openEditor()
  fireEvent.change(document.querySelector('textarea')!, { target: { value: '最新正文' } })
  await act(async () => { fireEvent.click(screen.getByRole('button', { name: '起标题' })) })
  expect(order).toEqual(['save', 'model'])
})

it('does not call the writing model when saving fails', async () => {
  vi.spyOn(api, 'patch').mockRejectedValue(new Error('offline'))
  const post = vi.spyOn(api, 'post')
  openEditor()
  await act(async () => { fireEvent.click(screen.getByRole('button', { name: '起标题' })) })
  expect(post).not.toHaveBeenCalled()
})

it('preserves a reopened draft when a save from the previous editor finishes', async () => {
  let finish!: (value: unknown) => void
  vi.spyOn(api, 'patch').mockImplementationOnce(() => new Promise((resolve) => { finish = resolve })).mockResolvedValue(doc)
  const first = openEditor()
  fireEvent.change(document.querySelector('textarea')!, { target: { value: '旧实例内容' } })
  await act(async () => { vi.advanceTimersByTime(1500) })
  first.unmount()
  const second = openEditor()
  fireEvent.change(document.querySelector('textarea')!, { target: { value: '重开后的新内容' } })
  await act(async () => { finish(doc) })
  second.unmount()
  openEditor()
  expect((document.querySelector('textarea') as HTMLTextAreaElement).value).toBe('重开后的新内容')
})

it('removes executable HTML and unsafe URLs from Markdown previews', () => {
  const { container } = render(<Markdown text={'## 正常标题\n<img src="x" onerror="alert(1)"><script>alert(1)</script>\n[危险链接](javascript:alert%281%29)'} />)
  expect(container.querySelector('h2')?.textContent).toBe('正常标题')
  expect(container.querySelector('script')).toBeNull()
  expect(container.querySelector('[onerror]')).toBeNull()
  expect(container.querySelector('a[href^="javascript:"]')).toBeNull()
})

it('flushes saves and locks manuscript inputs while adopting an Agent candidate', async () => {
  const candidate = { id: 'agent-run', document_id: doc.id, revision: 5, status: 'awaiting_adoption', running: false,
    state: { phase: 'variants', instruction: '', platforms: [], proposal: { title: 'Agent 标题', proposition: 'Agent 判断', sections: [], gaps: [], excerpts: [] }, drafts: [], draft_md: 'Agent 候选正文', review: null, variants: [], warnings: [], error: '' } }
  vi.spyOn(api, 'get').mockImplementation(async path => path.endsWith('/agent') ? candidate : { plan: { sections: [] } })
  const order: string[] = []
  vi.spyOn(api, 'patch').mockImplementation(async () => { order.push('save'); return doc })
  let finish!: (value: unknown) => void
  vi.spyOn(api, 'post').mockImplementation(() => { order.push('adopt'); return new Promise(resolve => { finish = resolve }) })
  openEditor()
  await act(async () => { fireEvent.click(screen.getByRole('button', { name: '创作 Agent' })) })
  await act(async () => { fireEvent.click(screen.getByRole('button', { name: /采用母稿/ })) })
  expect(order).toEqual(['save', 'adopt'])
  expect((document.querySelector('.editor-textarea') as HTMLTextAreaElement).disabled).toBe(true)
  await act(async () => { finish({ ...candidate, status: 'completed', revision: 6 }) })
  expect((document.querySelector('.editor-textarea') as HTMLTextAreaElement).value).toBe('Agent 候选正文')
  expect((document.querySelector('.editor-textarea') as HTMLTextAreaElement).disabled).toBe(false)
  expect((document.querySelector('.editor-title') as HTMLInputElement).value).toBe('Agent 标题')
  expect(localStorage.getItem(`draft.${doc.id}`)).toBeNull()
})
