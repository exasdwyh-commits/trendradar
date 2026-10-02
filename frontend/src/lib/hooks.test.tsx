// @vitest-environment jsdom
import { act, cleanup, renderHook, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { useFetch } from './hooks'

const fetchMock = vi.fn<typeof fetch>()
beforeEach(() => { vi.stubGlobal('fetch', fetchMock); fetchMock.mockReset() })
afterEach(() => { cleanup(); vi.unstubAllGlobals() })
const response = (value: unknown) => new Response(JSON.stringify(value))

it('cancels requests on navigation and ignores a late response from the old page', async () => {
  let resolveOld!: (value: Response) => void
  fetchMock.mockImplementationOnce(() => new Promise((resolve) => { resolveOld = resolve }))
    .mockResolvedValueOnce(response({ id: 'new' }))
  const { result, rerender, unmount } = renderHook(({ path }) => useFetch<{ id: string }>(path), {
    initialProps: { path: '/api/old' },
  })
  const oldSignal = fetchMock.mock.calls[0][1]?.signal
  rerender({ path: '/api/new' })
  expect(oldSignal?.aborted).toBe(true)
  await waitFor(() => expect(result.current.data?.id).toBe('new'))
  await act(async () => { resolveOld(response({ id: 'old' })) })
  expect(result.current.data?.id).toBe('new')
  const newSignal = fetchMock.mock.calls[1][1]?.signal
  unmount()
  expect(newSignal?.aborted).toBe(true)
})

it('clears data for a different resource while keeping data visible during reload', async () => {
  fetchMock.mockResolvedValueOnce(response({ id: 'old' }))
    .mockImplementation(() => new Promise(() => {}))
  const { result, rerender } = renderHook(({ path }) => useFetch<{ id: string }>(path), {
    initialProps: { path: '/api/old' },
  })
  await waitFor(() => expect(result.current.data?.id).toBe('old'))
  act(() => result.current.reload())
  expect(result.current.data?.id).toBe('old')
  expect(result.current.loading).toBe(true)
  rerender({ path: '/api/new' })
  expect(result.current.data).toBeNull()
})

it('clears old errors while retrying and resets state when disabled', async () => {
  fetchMock.mockRejectedValueOnce(new Error('unavailable'))
    .mockImplementation(() => new Promise(() => {}))
  const { result, rerender } = renderHook(({ path }) => useFetch(path), {
    initialProps: { path: '/api/old' as string | null },
  })
  await waitFor(() => expect(result.current.error).toBeInstanceOf(Error))
  act(() => result.current.reload())
  expect(result.current.error).toBeNull()
  rerender({ path: null })
  expect(result.current.loading).toBe(false)
  expect(result.current.data).toBeNull()
  expect(fetchMock.mock.calls[1][1]?.signal?.aborted).toBe(true)
})
