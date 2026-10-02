// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import App from './App'

vi.mock('./pages/Brief', () => ({ default: () => <h1>测试简报</h1> }))
vi.mock('./pages/Studio', () => ({ default: () => <h1>测试创作</h1> }))
vi.mock('./pages/Ask', () => { throw new Error('Failed to fetch dynamically imported module') })
beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn().mockImplementation(async () => new Response('null')))
  vi.stubGlobal('matchMedia', vi.fn().mockReturnValue({ matches: false }))
  const storage = new Map<string, string>()
  vi.stubGlobal('localStorage', {
    getItem: (key: string) => storage.get(key) ?? null,
    setItem: (key: string, value: string) => storage.set(key, value),
  })
})
afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks() })

it('shows a loading indicator while loading a route and keeps navigation available', async () => {
  render(<MemoryRouter><App /></MemoryRouter>)
  expect(screen.getByRole('status').textContent).toContain('正在加载页面')
  expect(await screen.findByRole('heading', { name: '工作台' })).toBeTruthy()
  fireEvent.click(screen.getByRole('link', { name: '稿件' }))
  expect(await screen.findByRole('heading', { name: '测试创作' })).toBeTruthy()
})

it('offers recovery after a route fails to load and allows navigation to another page', async () => {
  vi.spyOn(console, 'error').mockImplementation(() => {})
  render(<MemoryRouter initialEntries={['/ask']}><App /></MemoryRouter>)
  expect((await screen.findByRole('alert')).textContent).toContain('页面加载失败')
  expect(screen.getByRole('button', { name: '重新加载' })).toBeTruthy()
  fireEvent.click(screen.getByRole('link', { name: '选题简报' }))
  expect(await screen.findByRole('heading', { name: '测试简报' })).toBeTruthy()
  expect(screen.queryByRole('alert')).toBeNull()
})

it('refreshes sidebar counts when returning to another page', async () => {
  let healthCalls = 0
  vi.mocked(fetch).mockImplementation(async (url) => new Response(JSON.stringify(String(url) === '/api/health'
    ? { counts: { documents: ++healthCalls }, providers: { llm: {}, embedding: { degraded: false } }, version: '4.0.0' }
    : null)))
  render(<MemoryRouter><App /></MemoryRouter>)
  const manuscripts = await screen.findByRole('link', { name: /稿件\s*1/ })
  fireEvent.click(manuscripts)
  expect(await screen.findByRole('link', { name: /稿件\s*2/ })).toBeTruthy()
})

it('keeps advanced tools collapsed on small screens until explicitly opened', async () => {
  vi.stubGlobal('innerWidth', 390)
  render(<MemoryRouter><App /></MemoryRouter>)
  expect(await screen.findByRole('heading', { name: '工作台' })).toBeTruthy()
  expect(screen.queryByRole('link', { name: '痛点雷达' })).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: '扩展工具' }))
  expect(screen.getByRole('link', { name: '痛点雷达' })).toBeTruthy()
})
