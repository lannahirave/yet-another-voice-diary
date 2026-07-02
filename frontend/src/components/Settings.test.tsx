import { describe, expect, it, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { Settings } from './Settings'
import type { ApiConfig } from '../types/api'
import { setPipeline } from '../api/config'

const baseConfig: ApiConfig = {
  vad_threshold: 0.6,
  vad_negative_threshold: 0.45,
  vad_min_silence_ms: 300,
  vad_speech_pad_pre_ms: 300,
  vad_speech_pad_post_ms: 400,
  vad_speech_pad_ms: 200,
  vad_min_utterance_ms: 100,
  vad_max_utterance_ms: 13000,
  vad_model_id: 'silero',
  speaker_identification_threshold: 0.5,
  chunk_duration_ms: 100,
  unload_models_after_stop: false,
  preload_on_start: false,
  device: 'auto',
  providers: [
    { kind: 'asr', model_id: 'large-v3-turbo', state: 'UNLOADED', device: 'auto', error: null },
    { kind: 'embedding', model_id: 'ecapa', state: 'UNLOADED', device: 'auto', error: null },
    { kind: 'diarization', model_id: 'pyannote', state: 'UNLOADED', device: 'auto', error: null },
  ],
  blocklist_enabled: false,
  itn_enabled: true,
  itn_maps: [
    { filename: 'valid.json', label: 'valid', valid: true, variant_count: 2, error: null },
    { filename: 'bad.json', label: 'bad', valid: false, variant_count: 0, error: 'missing transliterations object' },
  ],
  itn_selected_maps: ['valid.json'],
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
}

vi.mock('../api/config', () => ({
  getConfig: vi.fn(async () => baseConfig),
  getStorageInfo: vi.fn(async () => ({
    db_path: 'test.db',
    db_size_bytes: 0,
    exists: false,
  })),
  selectProvider: vi.fn(async () => baseConfig),
  setBlocklistEnabled: vi.fn(async () => baseConfig),
  setElevenLabsToken: vi.fn(async () => baseConfig),
  setPipeline: vi.fn(async () => baseConfig),
  setPreloadOnStart: vi.fn(async () => baseConfig),
  setThreshold: vi.fn(async () => baseConfig),
  setUnloadAfterStop: vi.fn(async () => baseConfig),
}))

vi.mock('../api/models', () => ({
  getModelStatus: vi.fn(async () => ({})),
  loadModel: vi.fn(async () => undefined),
  unloadModel: vi.fn(async () => undefined),
}))

vi.mock('../api/contacts', () => ({
  listContacts: vi.fn(async () => []),
  createContact: vi.fn(async () => ({
    id: 'contact-1',
    name: 'Me',
    notes: '',
    created_at: new Date().toISOString(),
    profile_count: 0,
    session_count: 0,
    confidence: 0,
  })),
}))

function renderSettings() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <Settings />
    </QueryClientProvider>,
  )
}

describe('Settings', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders domain tabs and places ITN under Transcription', async () => {
    renderSettings()

    expect(await screen.findByTestId('settings-tab-providers')).toBeDefined()
    expect(screen.getByTestId('settings-tab-transcription')).toBeDefined()
    expect(screen.getByTestId('settings-tab-speech')).toBeDefined()
    expect(screen.getByTestId('settings-tab-speakers')).toBeDefined()
    expect(screen.getByTestId('settings-tab-runtime')).toBeDefined()
    expect(screen.getByTestId('settings-tab-storage')).toBeDefined()
    expect(screen.getByTestId('settings-tab-appearance')).toBeDefined()

    fireEvent.click(screen.getByTestId('settings-tab-transcription'))

    await waitFor(() => {
      expect(screen.getByTestId('itn-toggle')).toBeDefined()
    })
    expect(screen.getByText('settings.textCleanupSection')).toBeDefined()
    expect(screen.getByText('settings.itnEnabledLabel')).toBeDefined()
    expect(screen.getByTestId('itn-maps')).toBeDefined()
    expect(screen.queryByTestId('threshold-slider')).toBeNull()
  })

  it('renders ITN map selector and saves selected valid maps', async () => {
    renderSettings()

    fireEvent.click(await screen.findByTestId('settings-tab-transcription'))
    fireEvent.click(screen.getByTestId('itn-maps').querySelector('[role="combobox"]') as HTMLElement)

    expect(await screen.findByTestId('ms-option-valid.json')).toBeDefined()
    expect(screen.getByTestId('ms-option-bad.json').getAttribute('aria-disabled')).toBe('true')

    fireEvent.click(screen.getByTestId('ms-option-valid.json'))

    await waitFor(() => {
      expect(vi.mocked(setPipeline)).toHaveBeenCalledWith({ itn_selected_maps: [] })
    })
  })

  it('renders minimum utterance filter as a positive integer input', async () => {
    renderSettings()

    fireEvent.click(await screen.findByTestId('settings-tab-speech'))
    const input = await screen.findByTestId('vad-min-utterance-input')

    expect(input).toHaveProperty('value', '100')
    expect(input.getAttribute('type')).toBe('number')
    expect(input.getAttribute('min')).toBe('1')

    fireEvent.change(input, { target: { value: '75' } })
    fireEvent.blur(input)

    await waitFor(() => {
      expect(vi.mocked(setPipeline)).toHaveBeenCalledWith({ vad_min_utterance_ms: 75 })
    })
  })

  it('clamps minimum utterance filter input before saving', async () => {
    renderSettings()

    fireEvent.click(await screen.findByTestId('settings-tab-speech'))
    const input = await screen.findByTestId('vad-min-utterance-input')

    fireEvent.change(input, { target: { value: '-20' } })
    fireEvent.blur(input)

    await waitFor(() => {
      expect(vi.mocked(setPipeline)).toHaveBeenCalledWith({ vad_min_utterance_ms: 1 })
    })
  })
})
