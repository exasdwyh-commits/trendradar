// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes, useParams } from 'react-router-dom'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { api, type BriefItem, type DocumentSummary, type WorkbenchOverview } from '../lib/api'
import { ToastProvider } from '../components/toast'
import Workbench from './Workbench'

const doc: DocumentSummary = { id: 'current', title: '正在写的母稿', status: 'draft', thesis: '有证据的核心判断', target_platform: 'wechat', word_count: 900, data_mode: 'live', current_version: 2, created_at: '2026-10-01T00:00:00Z', updated_at: '2026-10-01T00:00:00Z', material_count: 2, variant_count: 0, publication_count: 0 }
const empty: WorkbenchOverview = { counts: { idea: 0, draft: 0, ready: 0, published: 0, archived: 0 }, resume: null, recent_documents: [], ready_documents: [], material_count: 0, recent_materials: [], topics: [], topic_count: 0, brief_day: '2026-10-01', today: '2026-10-02' }
beforeEach(() => { vi.spyOn(api, 'get').mockResolvedValue(empty) })
afterEach(() => { cleanup(); vi.restoreAllMocks() })
function Destination() { return <h1>编辑 {useParams().id}</h1> }
function open() {
  return render(<MemoryRouter><ToastProvider><Routes><Route path="/" element={<Workbench />} /><Route path="/studio/:id" element={<Destination />} /></Routes></ToastProvider></MemoryRouter>)
}

it('provides a direct resume link and real creation workflow counts', async () => {
  vi.mocked(api.get).mockResolvedValue({ ...empty, resume: doc, recent_documents: [doc], counts: { ...empty.counts, draft: 7, idea: 2, ready: 3 }, material_count: 11 })
  open()
  expect(await screen.findByRole('heading', { name: doc.title })).toBeTruthy()
  expect(screen.getByText('9 篇进行中')).toBeTruthy()
  expect(screen.getByText('3 篇待发布')).toBeTruthy()
  expect(screen.getByText('11 条素材')).toBeTruthy()
  expect(screen.getByRole('link', { name: '记一条笔记' }).getAttribute('href')).toBe('/materials?add=note')
  fireEvent.click(screen.getByRole('link', { name: '继续写作' }))
  expect(await screen.findByRole('heading', { name: '编辑 current' })).toBeTruthy()
})

it('does not create a draft until requested and prevents duplicate creates', async () => {
  let complete!: (value: { id: string }) => void
  const post = vi.spyOn(api, 'post').mockImplementation(() => new Promise((resolve) => { complete = resolve as typeof complete }))
  open()
  expect(await screen.findByRole('heading', { name: '给下一个想法留一页' })).toBeTruthy()
  expect(post).not.toHaveBeenCalled()
  const button = screen.getByRole('button', { name: '新建公众号母稿' })
  fireEvent.click(button)
  fireEvent.click(button)
  expect(post).toHaveBeenCalledTimes(1)
  expect(post).toHaveBeenCalledWith('/api/documents', { title: '', content_md: '', target_platform: 'wechat' })
  await act(async () => { complete({ id: 'new' }) })
  expect(await screen.findByRole('heading', { name: '编辑 new' })).toBeTruthy()
})

it('opens the grounded brief extension and reports a failed creation without navigating', async () => {
  const topic = { id: 'topic', title: '商业动态', angles: ['定价机制发生了什么变化'], origin: 'live', source_name: '真实来源', why: '机制值得分析', summary: '', status: 'new' } as BriefItem
  vi.mocked(api.get).mockResolvedValue({ ...empty, topics: [topic], topic_count: 1 })
  const post = vi.spyOn(api, 'post').mockRejectedValueOnce(new Error('服务暂时不可用')).mockResolvedValueOnce({ document_id: 'from-brief' })
  open()
  const button = await screen.findByRole('button', { name: '从这个切口开写' })
  fireEvent.click(button)
  expect(await screen.findByText('服务暂时不可用')).toBeTruthy()
  expect(screen.getByRole('heading', { name: '工作台' })).toBeTruthy()
  fireEvent.click(button)
  expect(post).toHaveBeenLastCalledWith('/api/brief/items/topic/extend', { angle: topic.angles[0] })
  expect(await screen.findByRole('heading', { name: '编辑 from-brief' })).toBeTruthy()
})
