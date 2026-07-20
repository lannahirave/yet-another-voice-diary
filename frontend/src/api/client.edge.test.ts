import { afterEach, describe, expect, it, vi } from 'vitest'
import { apiFetch } from './client'

describe('apiFetch edge cases', () => {
  afterEach(() => {
    vi.restoreAllMocks()
    vi.useRealTimers()
  })

  function hangingFetch() {
    return vi.fn().mockImplementation((_url: string, init: RequestInit) =>
      new Promise((_resolve, reject) => {
        init.signal?.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')))
      }),
    )
  }

  it('maps a caller abort to the same timeout error as an internal abort', async () => {
    vi.useFakeTimers()
    const fetchMock = hangingFetch()
    vi.stubGlobal('fetch', fetchMock)
    const caller = new AbortController()
    const addListener = vi.spyOn(caller.signal, 'addEventListener')
    const removeListener = vi.spyOn(caller.signal, 'removeEventListener')

    const request = apiFetch('/caller-abort', { signal: caller.signal })
    const passedSignal = fetchMock.mock.calls[0][1].signal as AbortSignal
    caller.abort()

    expect(passedSignal.aborted).toBe(true)
    const error = (await request.catch((err: unknown) => err as Error)) as Error
    expect(error).toBeInstanceOf(Error)
    expect(error.message).toContain('/caller-abort')
    expect(error.message).toMatch(/timeout|очікування/i)
    expect(caller.signal.aborted).toBe(true)
    expect(addListener).toHaveBeenCalledWith('abort', expect.any(Function), { once: true })
    expect(removeListener).toHaveBeenCalledWith('abort', expect.any(Function))
    expect(vi.getTimerCount()).toBe(0)
  })

  it('aborts only the internal signal on timeout and cleans up the caller listener', async () => {
    vi.useFakeTimers()
    const fetchMock = hangingFetch()
    vi.stubGlobal('fetch', fetchMock)
    const caller = new AbortController()
    const removeListener = vi.spyOn(caller.signal, 'removeEventListener')

    const request = apiFetch('/internal-timeout', { signal: caller.signal }, 25)
    const passedSignal = fetchMock.mock.calls[0][1].signal as AbortSignal
    const rejection = request.catch((err: unknown) => err as Error)
    await vi.advanceTimersByTimeAsync(25)

    const error = (await rejection) as Error
    expect(error.message).toContain('/internal-timeout')
    expect(error.message).toMatch(/timeout|очікування/i)
    expect(passedSignal.aborted).toBe(true)
    expect(caller.signal.aborted).toBe(false)
    expect(removeListener).toHaveBeenCalledWith('abort', expect.any(Function))
    expect(vi.getTimerCount()).toBe(0)
  })

  it('removes the caller listener and timeout after a successful response', async () => {
    vi.useFakeTimers()
    const caller = new AbortController()
    const removeListener = vi.spyOn(caller.signal, 'removeEventListener')
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve({ ok: true }),
    })
    vi.stubGlobal('fetch', fetchMock)

    await expect(apiFetch('/success', { signal: caller.signal }, 25)).resolves.toEqual({ ok: true })

    expect(removeListener).toHaveBeenCalledWith('abort', expect.any(Function))
    expect(vi.getTimerCount()).toBe(0)
  })
})
