import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderHook, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { getConfig } from '../api/config'
import { loadModel, unloadModel } from '../api/models'
import type { ApiConfig, ApiProviderStatus } from '../types/api'
import { queryKeys } from './keys'
import { useModelLifecycleMutation } from './config'

vi.mock('../api/config', () => ({
  getConfig: vi.fn(),
}))

vi.mock('../api/models', () => ({
  loadModel: vi.fn(),
  unloadModel: vi.fn(),
  getModelStatus: vi.fn(),
  getAvailableModels: vi.fn(),
}))

const provider = (state: string): ApiProviderStatus => ({
  kind: 'asr',
  model_id: 'large-v3-turbo',
  state,
  device: 'cpu',
  error: null,
})

const config = (state: string): ApiConfig => ({
  vad_threshold: 0.6,
  vad_negative_threshold: 0.45,
  vad_min_silence_ms: 300,
  vad_speech_pad_pre_ms: 300,
  vad_speech_pad_post_ms: 400,
  vad_speech_pad_ms: 200,
  vad_min_utterance_ms: 100,
  vad_max_utterance_ms: 8000,
  vad_model_id: 'silero',
  speaker_identification_threshold: 0.5,
  chunk_duration_ms: 100,
  unload_models_after_stop: false,
  preload_on_start: true,
  device: 'cpu',
  providers: [provider(state)],
  blocklist_enabled: true,
  itn_enabled: true,
  itn_maps: [],
  itn_selected_maps: [],
  elevenlabs_api_token_masked: 'not set',
  asr_no_speech_threshold: 0.6,
  asr_compression_ratio_threshold: 2.4,
  asr_repetition_penalty: 1.1,
  asr_no_repeat_ngram_size: 3,
  draft_enabled: false,
  draft_interval_ms: 5000,
  mic_self_contact_id: null,
  language_allowlist_enabled: false,
  language_allowlist: 'en,uk',
  language_confidence_threshold: 0.5,
})

function setup(initial: ApiConfig) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  client.setQueryData(queryKeys.config.current(), initial)
  const wrapper = ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  )
  return { client, wrapper }
}

describe('useModelLifecycleMutation', () => {
  it('updates both caches with the loaded provider status', async () => {
    const loaded = provider('LOADED')
    vi.mocked(loadModel).mockResolvedValueOnce(loaded)
    vi.mocked(getConfig).mockResolvedValueOnce(config('UNLOADED'))
    const { client, wrapper } = setup(config('UNLOADED'))
    const { result } = renderHook(() => useModelLifecycleMutation(), { wrapper })

    await result.current.mutateAsync({ type: 'asr', action: 'load' })

    expect(client.getQueryData(queryKeys.models.status())).toEqual({ asr: loaded })
    expect(client.getQueryData<ApiConfig>(queryKeys.config.current())?.providers[0].state).toBe('LOADED')
  })

  it('updates both caches with the unloaded provider status', async () => {
    const unloaded = provider('UNLOADED')
    vi.mocked(unloadModel).mockResolvedValueOnce(unloaded)
    vi.mocked(getConfig).mockResolvedValueOnce(config('LOADED'))
    const { client, wrapper } = setup(config('LOADED'))
    const { result } = renderHook(() => useModelLifecycleMutation(), { wrapper })

    await result.current.mutateAsync({ type: 'asr', action: 'unload' })

    expect(client.getQueryData(queryKeys.models.status())).toEqual({ asr: unloaded })
    expect(client.getQueryData<ApiConfig>(queryKeys.config.current())?.providers[0].state).toBe('UNLOADED')
  })

  it('leaves the caches unchanged when loading fails', async () => {
    const initial = config('UNLOADED')
    vi.mocked(loadModel).mockRejectedValueOnce(new Error('load failed'))
    const { client, wrapper } = setup(initial)
    const { result } = renderHook(() => useModelLifecycleMutation(), { wrapper })

    await expect(result.current.mutateAsync({ type: 'asr', action: 'load' })).rejects.toThrow('load failed')
    await waitFor(() => expect(client.getQueryData(queryKeys.config.current())).toBe(initial))
    expect(client.getQueryData(queryKeys.models.status())).toBeUndefined()
  })
})
