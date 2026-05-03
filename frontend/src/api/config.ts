import type { ApiConfig, ApiStorageInfo } from '../types/api'
import { apiFetch } from './client'

export const getConfig = () => apiFetch<ApiConfig>('/config')

export const setThreshold = (_type: 'vad' | 'speaker', value: number) =>
  apiFetch<ApiConfig>('/config/threshold', {
    method: 'POST',
    body: JSON.stringify({ value }),
  })

export const selectProvider = (type: string, modelId: string) =>
  apiFetch<ApiConfig>(`/config/provider/${type}`, {
    method: 'POST',
    body: JSON.stringify({ model_id: modelId }),
  })

export const setUnloadAfterStop = (value: boolean) =>
  apiFetch<ApiConfig>('/config/unload-after-stop', {
    method: 'POST',
    body: JSON.stringify({ value }),
  })

export const setPreloadOnStart = (value: boolean) =>
  apiFetch<ApiConfig>('/config/preload-on-start', {
    method: 'POST',
    body: JSON.stringify({ value }),
  })

export const setBlocklistEnabled = (value: boolean) =>
  apiFetch<ApiConfig>('/config/blocklist', {
    method: 'POST',
    body: JSON.stringify({ value }),
  })

export const setElevenLabsToken = (token: string) =>
  apiFetch<ApiConfig>('/config/elevenlabs-token', {
    method: 'POST',
    body: JSON.stringify({ token }),
  })

export const getStorageInfo = () => apiFetch<ApiStorageInfo>('/config/storage')
