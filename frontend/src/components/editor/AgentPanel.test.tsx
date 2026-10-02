// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { api } from '../../lib/api'
import AgentPanel from './AgentPanel'

const proposal = { title: '候选标题', audience: '公众号读者', question: '为什么发生？', proposition: '核心判断', gaps: ['还缺成本依据'], excerpts: [], sections: [{ id: 'one', title: '机制', goal: '解释机制', target_words: 400, evidence_ids: [], content_md: '' }] }
const run = { id: 'run', document_id: 'doc', revision: 0, status: 'planning', running: false, state: { phase: 'planning', instruction: '', platforms: [], proposal: null, drafts: [], draft_md: '', review: null, variants: [], warnings: [], error: '' } }
const outline = { ...run, revision: 1, status: 'awaiting_outline', state: { ...run.state, proposal } }
beforeEach(() => { vi.spyOn(api, 'get').mockResolvedValue(null) })
afterEach(() => { cleanup(); vi.restoreAllMocks() })
const before = vi.fn(async () => true)
const adopt = vi.fn()
function open(active = true) { return render(<AgentPanel documentId="doc" active={active} available beforeAction={before} adopt={adopt} />) }

it('never starts paid work on mount and stops at outline confirmation', async () => {
  const post = vi.spyOn(api, 'post').mockResolvedValueOnce(run).mockResolvedValueOnce(outline)
  open()
  const button = await screen.findByRole('button', { name: '整理素材并规划' })
  expect(post).not.toHaveBeenCalled()
  fireEvent.click(button)
  expect(await screen.findByText('还缺成本依据')).toBeTruthy()
  expect(screen.getByRole('button', { name: '确认大纲并连续起草' })).toBeTruthy()
  expect(post).toHaveBeenCalledTimes(2)
})

it('continues through model steps and waits for explicit manuscript adoption', async () => {
  vi.mocked(api.get).mockResolvedValue(outline)
  const drafting = { ...outline, revision: 2, status: 'drafting', state: { ...outline.state, phase: 'drafting' } }
  const candidate = { ...drafting, revision: 3, status: 'awaiting_adoption', state: { ...drafting.state, draft_md: '候选正文' } }
  const post = vi.spyOn(api, 'post').mockResolvedValueOnce(drafting).mockResolvedValueOnce(candidate)
  open()
  fireEvent.click(await screen.findByRole('button', { name: '确认大纲并连续起草' }))
  expect(await screen.findByText('候选正文')).toBeTruthy()
  expect(adopt).not.toHaveBeenCalled()
  expect(post).toHaveBeenCalledTimes(2)
  adopt.mockResolvedValueOnce({ ...candidate, status: 'completed' })
  fireEvent.click(screen.getByRole('button', { name: /采用母稿/ }))
  expect(await screen.findByText('已采用到正文')).toBeTruthy()
  expect(adopt).toHaveBeenCalledTimes(1)
})

it('pauses after the in-flight step when the panel is hidden', async () => {
  const drafting = { ...outline, status: 'drafting', state: { ...outline.state, phase: 'drafting' } }
  vi.mocked(api.get).mockResolvedValue(drafting)
  let complete!: (value: unknown) => void
  const post = vi.spyOn(api, 'post').mockImplementation(() => new Promise(resolve => { complete = resolve }))
  const view = open()
  fireEvent.click(await screen.findByRole('button', { name: '继续执行' }))
  await waitFor(() => expect(post).toHaveBeenCalledTimes(1))
  view.rerender(<AgentPanel documentId="doc" active={false} available beforeAction={before} adopt={adopt} />)
  await act(async () => { complete({ ...drafting, revision: 2, status: 'reviewing', state: { ...drafting.state, phase: 'reviewing' } }) })
  expect(post).toHaveBeenCalledTimes(1)
})

it('shows failed progress without automatically retrying and stops when a save fails', async () => {
  const post = vi.spyOn(api, 'post').mockResolvedValueOnce(run).mockResolvedValueOnce({ ...run, revision: 1, status: 'failed', state: { ...run.state, error: '额度已用完' } })
  open()
  fireEvent.click(await screen.findByRole('button', { name: '整理素材并规划' }))
  expect(await screen.findByText('额度已用完')).toBeTruthy()
  expect(post).toHaveBeenCalledTimes(2)
  before.mockResolvedValueOnce(false)
  fireEvent.click(screen.getByRole('button', { name: '重试当前步骤' }))
  expect(await screen.findByText('请先成功保存当前稿件，再执行 Agent。')).toBeTruthy()
  expect(post).toHaveBeenCalledTimes(2)
})
