import i18n from '../i18n'

export const BASE_URL = 'http://127.0.0.1:8765'
export const WS_URL = 'ws://127.0.0.1:8765'

const REQUEST_TIMEOUT_MS = 10_000

function toApiError(path: string, err: unknown): Error {
  const t = i18n.t.bind(i18n)
  const backendUnavailable = t('api.backendUnavailable')
  if (err instanceof DOMException && err.name === 'AbortError') {
    return new Error(`${backendUnavailable} ${t('api.requestTimeout', { path })}`)
  }
  if (err instanceof TypeError) {
    return new Error(`${backendUnavailable} ${t('api.connectFailed')}`)
  }
  return err instanceof Error ? err : new Error(t('api.unknownError'))
}

export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const controller = new AbortController()
  const timeout = window.setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS)
  const abortFromCaller = () => controller.abort()
  init?.signal?.addEventListener('abort', abortFromCaller, { once: true })

  try {
    const res = await fetch(`${BASE_URL}${path}`, {
      ...init,
      headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
      signal: controller.signal,
    })
    if (!res.ok) throw new Error(`API ${res.status} ${path}: ${await res.text()}`)
    if (res.status === 204) return undefined as T
    return res.json() as Promise<T>
  } catch (err) {
    throw toApiError(path, err)
  } finally {
    window.clearTimeout(timeout)
    init?.signal?.removeEventListener('abort', abortFromCaller)
  }
}
