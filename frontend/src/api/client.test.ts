import { describe, expect, it, vi, beforeEach } from 'vitest'
import { apiFetch } from './client'

describe('apiFetch', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  it('parses JSON response', async () => {
    const mockFetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve({ data: 'hello' }),
    })
    vi.stubGlobal('fetch', mockFetch)

    const result = await apiFetch<{ data: string }>('/test')
    expect(result).toEqual({ data: 'hello' })
    expect(mockFetch).toHaveBeenCalledWith(
      expect.stringContaining('/test'),
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    )
  })

  it('returns undefined for 204 responses', async () => {
    const mockFetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 204,
    })
    vi.stubGlobal('fetch', mockFetch)

    const result = await apiFetch('/test')
    expect(result).toBeUndefined()
  })

  it('throws on non-ok response', async () => {
    const mockFetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 500,
      text: () => Promise.resolve('Internal error'),
    })
    vi.stubGlobal('fetch', mockFetch)

    await expect(apiFetch('/test')).rejects.toThrow('API 500 /test')
  })

  it('throws on request timeout', async () => {
    vi.useFakeTimers()

    const mockFetch = vi.fn().mockImplementation(
      () => new Promise((_, reject) => {
        // Simulate abort via AbortController timeout
        const err = new DOMException('The operation was aborted.', 'AbortError')
        reject(err)
      }),
    )
    vi.stubGlobal('fetch', mockFetch)

    const promise = apiFetch('/test')
    vi.advanceTimersByTime(10001)

    await expect(promise).rejects.toThrow()
    vi.useRealTimers()
  })

  it('throws on network error (TypeError)', async () => {
    const mockFetch = vi.fn().mockRejectedValue(new TypeError('Failed to fetch'))
    vi.stubGlobal('fetch', mockFetch)

    await expect(apiFetch('/test')).rejects.toThrow()
  })

  it('forwards custom headers', async () => {
    const mockFetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve({}),
    })
    vi.stubGlobal('fetch', mockFetch)

    await apiFetch('/test', { method: 'POST', headers: { 'X-Custom': 'value' } })

    const callArgs = mockFetch.mock.calls[0][1]
    expect(callArgs.method).toBe('POST')
    expect(callArgs.headers['Content-Type']).toBe('application/json')
    expect(callArgs.headers['X-Custom']).toBe('value')
  })

  it('cleans up timeout on success', async () => {
    const mockFetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve({}),
    })
    vi.stubGlobal('fetch', mockFetch)
    const clearTimeoutSpy = vi.spyOn(window, 'clearTimeout')

    await apiFetch('/test')

    expect(clearTimeoutSpy).toHaveBeenCalled()
  })
})
