// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { api } from '../lib/api'
import { TranslationPanel } from './translation'

const translated = { title: '机器人报告', content: '销量增长 20%。', original_title: 'Robot report', original_content: 'Sales grew 20%.', model: 'mimo-v2.6-pro', warnings: [], cached: true, origin: 'live' }
const title = { ...translated, content: '', original_content: '', model: 'agnes-3.0-flash' }
beforeEach(() => { vi.spyOn(api, 'get').mockResolvedValue(title) })
afterEach(() => { cleanup(); vi.restoreAllMocks() })
const open = () => render(<TranslationPanel refType="signal" refId="article" originalContent="Sales grew 20%." />)

it('shows only a translated title until the reader requests the full article', async () => {
  const post = vi.spyOn(api, 'post').mockResolvedValue(translated)
  open()
  expect(await screen.findByText('机器人报告')).toBeTruthy()
  expect(screen.getByText('Sales grew 20%.')).toBeTruthy()
  expect(post).not.toHaveBeenCalled()
  fireEvent.click(screen.getByText('翻译全文'))
  expect(await screen.findByText('销量增长 20%。')).toBeTruthy()
  expect(post).toHaveBeenCalledWith('/api/translations/signal/article?scope=full')
  fireEvent.click(screen.getByText('英文原文'))
  expect(screen.getByText('Sales grew 20%.')).toBeTruthy()
  expect(screen.queryByText('销量增长 20%。')).toBeNull()
})

it('automatically requests only the title when it is not cached', async () => {
  vi.mocked(api.get).mockResolvedValue(null)
  const post = vi.spyOn(api, 'post').mockResolvedValue(title)
  open()
  expect(await screen.findByText('机器人报告')).toBeTruthy()
  expect(post).toHaveBeenCalledTimes(1)
  expect(post).toHaveBeenCalledWith('/api/translations/signal/article?scope=title')
  expect(screen.queryByText('销量增长 20%。')).toBeNull()
})

it('keeps the title and original visible after a full translation failure', async () => {
  vi.spyOn(api, 'post').mockRejectedValue(new Error('翻译服务不可用'))
  open()
  expect(await screen.findByText('机器人报告')).toBeTruthy()
  fireEvent.click(screen.getByText('翻译全文'))
  expect(await screen.findByRole('alert')).toBeTruthy()
  expect(screen.getByText('Sales grew 20%.')).toBeTruthy()
  expect((screen.getByText('翻译全文') as HTMLButtonElement).disabled).toBe(false)
})
