import { useEffect, useMemo, useState } from 'react'
import type { CSSProperties, ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import {
  useBlocklistEnabledMutation,
  useConfigQuery,
  useElevenLabsTokenMutation,
  useModelLifecycleMutation,
  useModelProgress,
  usePreloadOnStartMutation,
  useSelectProviderMutation,
  useSetPipelineMutation,
  useSetThresholdMutation,
  useStorageInfoQuery,
  useUnloadAfterStopMutation,
} from '../query/config'
import type { ApiProviderStatus } from '../types/api'
import { Toggle } from './shared/Toggle'
import { MultiSelect } from './shared/MultiSelect'
import type { MultiSelectOption } from './shared/MultiSelect'
import { ContactPicker } from './shared/ContactPicker'

type ModelState =
  | 'LOADED'
  | 'UNLOADED'
  | 'LOADING'
  | 'NOT_DOWNLOADED'
  | 'AVAILABLE'
  | 'ERROR'

type ProviderKind = 'asr' | 'embedding' | 'diarization' | 'vad'
type SectionId =
  | 'providers'
  | 'transcription'
  | 'speech'
  | 'speakers'
  | 'runtime'
  | 'storage'
  | 'appearance'

const STATE_COLORS: Record<ModelState, string> = {
  LOADED: 'var(--green)',
  UNLOADED: 'var(--text-dim)',
  LOADING: 'var(--amber)',
  NOT_DOWNLOADED: 'var(--text-dim)',
  AVAILABLE: 'var(--text-dim)',
  ERROR: 'var(--record)',
}

const STATE_LABEL_KEYS: Record<ModelState, string> = {
  LOADED: 'settings.stateLOADED',
  UNLOADED: 'settings.stateUNLOADED',
  LOADING: 'settings.stateLOADING',
  NOT_DOWNLOADED: 'settings.stateNOT_DOWNLOADED',
  AVAILABLE: 'settings.stateAVAILABLE',
  ERROR: 'settings.stateERROR',
}

interface ModelDef {
  id: string
  name: string
  size: string
  speed: string
  quality: string
}

interface ModelCardProps {
  model: ModelDef
  state: ModelState
  selected: boolean
  disabled: boolean
  buttonLabel: string
  onSelect: () => void
  lifecycleLabel?: string
  lifecycleDisabled?: boolean
  onLifecycle?: () => void
  errorMessage?: string | null
  kind?: string
}

const ASR_MODELS: ModelDef[] = [
  {
    id: 'elevenlabs-scribe',
    name: 'ElevenLabs Scribe',
    size: 'cloud',
    speed: '',
    quality: 'settings.qualityRecommended',
  },
  {
    id: 'tiny',
    name: 'whisper tiny',
    size: '~39 MB',
    speed: '',
    quality: '',
  },
  {
    id: 'medium',
    name: 'whisper medium',
    size: '~1.5 GB',
    speed: '',
    quality: 'settings.qualityGood',
  },
  {
    id: 'large-v3-turbo',
    name: 'whisper large-v3-turbo',
    size: '~1.6 GB',
    speed: '',
    quality: 'settings.qualityRecommended',
  },
]

const EMBED_MODELS: ModelDef[] = [
  {
    id: 'ecapa',
    name: 'ECAPA-TDNN',
    size: '~85 MB',
    speed: '',
    quality: 'settings.qualityRecommendedM',
  },
  {
    id: 'wavlm',
    name: 'WavLM Large',
    size: '~1.3 GB',
    speed: '',
    quality: 'settings.qualityAccurate',
  },
]

const DIAR_MODELS: ModelDef[] = [
  {
    id: 'pyannote',
    name: 'PyAnnote 3.1',
    size: '~270 MB',
    speed: '',
    quality: 'settings.qualityRecommended',
  },
  {
    id: 'sortformer-v2.1',
    name: 'NVIDIA Streaming Sortformer 4spk v2.1',
    size: '—',
    speed: '',
    quality: 'settings.qualityAlternative',
  },
]

const LANGUAGE_OPTIONS: MultiSelectOption[] = [
  { value: 'en', label: 'English (en)' },
  { value: 'uk', label: 'Ukrainian (uk)' },
  { value: 'de', label: 'German (de)' },
  { value: 'fr', label: 'French (fr)' },
  { value: 'es', label: 'Spanish (es)' },
  { value: 'it', label: 'Italian (it)' },
  { value: 'pl', label: 'Polish (pl)' },
  { value: 'cs', label: 'Czech (cs)' },
  { value: 'sk', label: 'Slovak (sk)' },
  { value: 'ro', label: 'Romanian (ro)' },
  { value: 'hu', label: 'Hungarian (hu)' },
  { value: 'tr', label: 'Turkish (tr)' },
  { value: 'ar', label: 'Arabic (ar)' },
  { value: 'he', label: 'Hebrew (he)' },
  { value: 'zh', label: 'Chinese (zh)' },
  { value: 'ja', label: 'Japanese (ja)' },
  { value: 'ko', label: 'Korean (ko)' },
  { value: 'hi', label: 'Hindi (hi)' },
  { value: 'pt', label: 'Portuguese (pt)' },
  { value: 'nl', label: 'Dutch (nl)' },
  { value: 'sv', label: 'Swedish (sv)' },
  { value: 'da', label: 'Danish (da)' },
  { value: 'no', label: 'Norwegian (no)' },
  { value: 'fi', label: 'Finnish (fi)' },
]

const sectionsBase: Array<{ id: SectionId; labelKey: string }> = [
  { id: 'providers', labelKey: 'settings.tabModels' },
  { id: 'transcription', labelKey: 'settings.tabTranscription' },
  { id: 'speech', labelKey: 'settings.tabSpeechDetection' },
  { id: 'speakers', labelKey: 'settings.tabSpeakerIdentification' },
  { id: 'runtime', labelKey: 'settings.tabRuntime' },
  { id: 'storage', labelKey: 'settings.tabStorage' },
  { id: 'appearance', labelKey: 'settings.tabAppearance' },
]

function formatBytes(n: number): string {
  if (!Number.isFinite(n) || n <= 0) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let v = n
  let i = 0
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024
    i++
  }
  return `${v.toFixed(v >= 100 ? 0 : v >= 10 ? 1 : 2)} ${units[i]}`
}

function ModelCard({
  model,
  state,
  selected,
  disabled,
  buttonLabel,
  onSelect,
  lifecycleLabel,
  lifecycleDisabled,
  onLifecycle,
  errorMessage,
  kind,
}: ModelCardProps) {
  const { t } = useTranslation()
  const buttonDisabled = disabled || selected
  const baseLabel = t(STATE_LABEL_KEYS[state])
  const stateLabel = baseLabel
  const qualityLabel = t(model.quality, { defaultValue: model.quality })

  const handleSelect = () => {
    if (buttonDisabled) return
    onSelect()
  }

  return (
    <div
      data-testid={kind ? `model-card-${kind}-${model.id}` : undefined}
      onClick={handleSelect}
      style={{
        ...stS.modelCard,
        ...(selected ? stS.modelCardSel : {}),
        ...(disabled ? stS.modelCardDisabled : {}),
      }}
    >
      {selected && <div style={stS.modelCheck}>✓</div>}
      <div style={stS.modelTop}>
        <span style={stS.modelName}>{model.name}</span>
      </div>
      <div style={stS.modelMeta}>
        <span style={{ color: STATE_COLORS[state], fontWeight: 500 }}>
          ● {stateLabel}
        </span>
        <span style={{ color: 'var(--border-str)' }}>·</span>
        <span>{model.size}</span>
        <span style={{ color: 'var(--border-str)' }}>·</span>
        <span style={{ color: 'var(--text-muted)' }}>{qualityLabel}</span>
      </div>
      {state === 'ERROR' && errorMessage && (
        <div style={stS.modelError}>{errorMessage}</div>
      )}
      <div style={stS.modelActions}>
        <button
          data-testid={kind ? `select-${kind}` : undefined}
          onClick={(e) => {
            e.stopPropagation()
            handleSelect()
          }}
          disabled={buttonDisabled}
          style={{
            ...stS.modelBtn,
            ...(selected ? stS.modelBtnSelected : stS.modelBtnIdle),
            ...(buttonDisabled ? stS.modelBtnDisabled : {}),
          }}
        >
          {buttonLabel}
        </button>
        {selected && lifecycleLabel && onLifecycle && (
          <button
            data-testid={kind ? (state === 'LOADED' ? `unload-${kind}` : `load-${kind}`) : undefined}
            onClick={(e) => {
              e.stopPropagation()
              onLifecycle()
            }}
            disabled={lifecycleDisabled}
            style={{
              ...stS.modelBtn,
              ...stS.modelBtnIdle,
              ...(lifecycleDisabled ? stS.modelBtnDisabled : {}),
            }}
          >
            {lifecycleLabel}
          </button>
        )}
      </div>
    </div>
  )
}

function Divider() {
  return (
    <div
      style={{ height: 1, background: 'var(--border)', margin: '8px 0' }}
    />
  )
}

interface SectionTitleProps {
  children: ReactNode
  mt?: number
}

function SectionTitle({ children, mt }: SectionTitleProps) {
  return (
    <div
      style={{
        fontSize: 13.5,
        fontWeight: 600,
        color: 'var(--text)',
        marginBottom: 14,
        marginTop: mt ?? 0,
        paddingBottom: 10,
        borderBottom: '1px solid var(--border)',
      }}
    >
      {children}
    </div>
  )
}

function isProviderKind(kind: string): kind is ProviderKind {
  return kind === 'asr' || kind === 'embedding' || kind === 'diarization'
}

function normalizeModelState(state?: string): ModelState {
  switch (state) {
    case 'LOADED':
      return 'LOADED'
    case 'UNLOADED':
      return 'UNLOADED'
    case 'LOADING':
    case 'DOWNLOADING':
      return 'LOADING'
    case 'NOT_DOWNLOADED':
      return 'NOT_DOWNLOADED'
    case 'ERROR':
      return 'ERROR'
    default:
      return 'AVAILABLE'
  }
}

function configErrorMessage(
  error: unknown,
  fallback: string,
  t: (k: string) => string,
): string {
  if (!(error instanceof Error)) return fallback
  if (error.message.includes('Failed to fetch')) return t('settings.backendUnavailable')
  const match = error.message.match(/^API \d+ \S+: (.+)$/s)
  return match?.[1]?.trim() || fallback
}

function withCurrentFallback(
  models: ModelDef[],
  provider?: ApiProviderStatus,
): ModelDef[] {
  if (!provider?.model_id) return models
  if (models.some((model) => model.id === provider.model_id)) return models
  return [
    ...models,
    {
      id: provider.model_id,
      name: provider.model_id,
      size: '—',
      speed: '—',
      quality: 'settings.qualityCurrent',
    },
  ]
}

function providerCardState(
  provider: ApiProviderStatus | undefined,
  modelId: string,
): ModelState {
  if (provider?.model_id === modelId) return normalizeModelState(provider.state)
  return 'AVAILABLE'
}

export function Settings() {
  const { t, i18n: i18nInstance } = useTranslation()
  const [theme, setThemeState] = useState<string>(() => {
    try {
      return localStorage.getItem('vd-theme') || 'light'
    } catch {
      return 'light'
    }
  })
  const sections = sectionsBase.map((section) => ({ id: section.id, label: t(section.labelKey) }))
  const [active, setActive] = useState<SectionId>('providers')
  const [threshold, setThresholdValue] = useState(0.5)
  const [actionError, setActionError] = useState<string | null>(null)
  const [savingProvider, setSavingProvider] = useState<ProviderKind | null>(null)
  const [savingThreshold, setSavingThreshold] = useState(false)
  const [savingUnload, setSavingUnload] = useState(false)
  const [savingPreload, setSavingPreload] = useState(false)
  const [savingBlocklist, setSavingBlocklist] = useState(false)
  const [savingELToken, setSavingELToken] = useState(false)
  const [editingToken, setEditingToken] = useState(false)
  const [tokenDraft, setTokenDraft] = useState('')
  const [modelAction, setModelAction] = useState<ProviderKind | null>(null)
  const _diarProgress = useModelProgress('diarization')
  const _asrProgress = useModelProgress('asr')
  const _embProgress = useModelProgress('embedding')
  const _vadProgress = useModelProgress('vad')
  void _diarProgress; void _asrProgress; void _embProgress; void _vadProgress

  // VAD pipeline local state
  const [vadOnset, setVadOnset] = useState(0.60)
  const [vadOffset, setVadOffset] = useState(0.45)
  const [vadMinSilence, setVadMinSilence] = useState(300)
  const [vadPadPre, setVadPadPre] = useState(300)
  const [vadPadPost, setVadPadPost] = useState(400)
  const [vadMinUtt, setVadMinUtt] = useState(300)
  const [vadMaxUtt, setVadMaxUtt] = useState(13_000)
  const [savingPipeline, setSavingPipeline] = useState(false)

  // ASR quality gate local state
  const [asrNoSpeech, setAsrNoSpeech] = useState(0.6)
  const [asrCompression, setAsrCompression] = useState(2.4)
  const [asrRepPenalty, setAsrRepPenalty] = useState(1.1)
  const [asrNgram, setAsrNgram] = useState(3)
  const [draftEnabled, setDraftEnabled] = useState(false)
  const [micSelfContactId, setMicSelfContactId] = useState<string | null>(null)
  const [langAllowlistEnabled, setLangAllowlistEnabled] = useState(false)
  const [langAllowlist, setLangAllowlist] = useState<string[]>(['en', 'uk'])
  const [langConfidenceThreshold, setLangConfidenceThreshold] = useState(0.5)
  const [itnEnabled, setItnEnabled] = useState(true)
  const [itnSelectedMaps, setItnSelectedMaps] = useState<string[]>([])

  const configQuery = useConfigQuery()
  const storageQuery = useStorageInfoQuery()
  const selectProviderMutation = useSelectProviderMutation()
  const setThresholdMutation = useSetThresholdMutation()
  const unloadAfterStopMutation = useUnloadAfterStopMutation()
  const preloadOnStartMutation = usePreloadOnStartMutation()
  const blocklistEnabledMutation = useBlocklistEnabledMutation()
  const elevenLabsTokenMutation = useElevenLabsTokenMutation()
  const modelLifecycleMutation = useModelLifecycleMutation()
  const setPipelineMutation = useSetPipelineMutation()

  const config = configQuery.data ?? null
  const loadingConfig = configQuery.isLoading
  const configError = actionError
    ?? (configQuery.error ? configErrorMessage(configQuery.error, t('settings.errLoadConfig'), t) : null)

  useEffect(() => {
    if (config) {
      setThresholdValue(config.speaker_identification_threshold)
      setVadOnset(config.vad_threshold)
      setVadOffset(config.vad_negative_threshold)
      setVadMinSilence(config.vad_min_silence_ms)
      setVadPadPre(config.vad_speech_pad_pre_ms)
      setVadPadPost(config.vad_speech_pad_post_ms)
      setVadMinUtt(config.vad_min_utterance_ms)
      setVadMaxUtt(config.vad_max_utterance_ms)
      setAsrNoSpeech(config.asr_no_speech_threshold)
      setAsrCompression(config.asr_compression_ratio_threshold)
      setAsrRepPenalty(config.asr_repetition_penalty)
      setAsrNgram(config.asr_no_repeat_ngram_size)
      setDraftEnabled(config.draft_enabled ?? false)
      setMicSelfContactId(config.mic_self_contact_id ?? null)
      setLangAllowlistEnabled(config.language_allowlist_enabled ?? false)
      setLangAllowlist((config.language_allowlist ?? 'en,uk').split(',').map((s) => s.trim()).filter(Boolean))
      setLangConfidenceThreshold(config.language_confidence_threshold ?? 0.5)
      setItnEnabled(config.itn_enabled ?? true)
      setItnSelectedMaps(config.itn_selected_maps ?? [])
      setActionError(null)
    }
  }, [config])

  const providers = useMemo(() => {
    const next: Partial<Record<ProviderKind, ApiProviderStatus>> = {}
    for (const provider of config?.providers ?? []) {
      if (isProviderKind(provider.kind)) next[provider.kind] = provider
    }
    return next
  }, [config])

  const asrProvider = providers.asr
  const embeddingProvider = providers.embedding
  const diarizationProvider = providers.diarization

  const asrModels = withCurrentFallback(ASR_MODELS, asrProvider)
  const embeddingModels = withCurrentFallback(EMBED_MODELS, embeddingProvider)
  const diarizationModels = withCurrentFallback(DIAR_MODELS, diarizationProvider)

  const selectedAsrModel = asrProvider?.model_id ?? 'large-v3-turbo'
  const selectedEmbeddingModel = embeddingProvider?.model_id ?? 'ecapa'
  const selectedDiarizationModel = diarizationProvider?.model_id ?? 'pyannote'
  const itnMapOptions = useMemo<MultiSelectOption[]>(
    () =>
      (config?.itn_maps ?? []).map((map) => ({
        value: map.filename,
        label: map.valid
          ? `${map.label} (${map.variant_count})`
          : `${map.label} (${t('settings.invalid')})`,
        helperText: map.valid ? map.filename : (map.error ?? map.filename),
        disabled: !map.valid,
      })),
    [config?.itn_maps, t],
  )
  const thresholdColor =
    threshold > 0.7
      ? 'var(--amber)'
      : threshold < 0.45
        ? 'var(--record)'
        : 'var(--green)'

  const handleProviderSelect = async (kind: ProviderKind, modelId: string) => {
    const currentModelId = providers[kind]?.model_id
    if (!config || savingProvider || currentModelId === modelId) return

    setSavingProvider(kind)
    setActionError(null)
    try {
      await selectProviderMutation.mutateAsync({ type: kind, modelId })
    } catch (error) {
      setActionError(configErrorMessage(error, t('settings.errUpdateProvider'), t))
    } finally {
      setSavingProvider(null)
    }
  }

  const handleModelLifecycle = async (kind: ProviderKind) => {
    const provider = providers[kind]
    if (!provider || modelAction) return

    setModelAction(kind)
    setActionError(null)
    try {
      await modelLifecycleMutation.mutateAsync({
        type: kind,
        action: normalizeModelState(provider.state) === 'LOADED' ? 'unload' : 'load',
      })
    } catch (error) {
      setActionError(configErrorMessage(error, t('settings.errChangeModelState'), t))
    } finally {
      setModelAction(null)
    }
  }

  const lifecycleLabel = (kind: ProviderKind, state: ModelState) => {
    if (modelAction === kind) return t('settings.btnUpdating')
    if (state === 'LOADED') return t('settings.btnUnload')
    if (state === 'LOADING') return t('settings.btnLoading')
    if (state === 'ERROR') return t('settings.btnRetry')
    return t('settings.btnLoad')
  }

  const commitThreshold = async (nextValue: number) => {
    const previousValue = config?.speaker_identification_threshold
    if (!config || savingThreshold || previousValue === undefined) return
    if (Math.abs(nextValue - previousValue) < 0.001) return

    setSavingThreshold(true)
    setActionError(null)
    try {
      await setThresholdMutation.mutateAsync(nextValue)
    } catch (error) {
      setThresholdValue(previousValue)
      setActionError(configErrorMessage(error, t('settings.errSaveThreshold'), t))
    } finally {
      setSavingThreshold(false)
    }
  }

  const commitUnloadAfterStop = async (next: boolean) => {
    if (!config || savingUnload) return
    setSavingUnload(true)
    setActionError(null)
    try {
      await unloadAfterStopMutation.mutateAsync(next)
    } catch (error) {
      setActionError(configErrorMessage(error, t('settings.errSaveSetting'), t))
    } finally {
      setSavingUnload(false)
    }
  }

  const commitPreloadOnStart = async (next: boolean) => {
    if (!config || savingPreload) return
    setSavingPreload(true)
    setActionError(null)
    try {
      await preloadOnStartMutation.mutateAsync(next)
    } catch (error) {
      setActionError(configErrorMessage(error, t('settings.errSaveSetting'), t))
    } finally {
      setSavingPreload(false)
    }
  }

  const commitBlocklistEnabled = async (next: boolean) => {
    if (!config || savingBlocklist) return
    setSavingBlocklist(true)
    setActionError(null)
    try {
      await blocklistEnabledMutation.mutateAsync(next)
    } catch (error) {
      setActionError(configErrorMessage(error, t('settings.errSaveSetting'), t))
    } finally {
      setSavingBlocklist(false)
    }
  }

  const commitPipeline = async (fields: Record<string, number | boolean | string | string[] | null>) => {
    if (!config || savingPipeline) return
    setSavingPipeline(true)
    setActionError(null)
    try {
      await setPipelineMutation.mutateAsync(fields)
    } catch (error) {
      setActionError(configErrorMessage(error, t('settings.errSaveSetting'), t))
    } finally {
      setSavingPipeline(false)
    }
  }

  const commitElevenLabsToken = async () => {
    if (!config || savingELToken) return
    setSavingELToken(true)
    setActionError(null)
    try {
      await elevenLabsTokenMutation.mutateAsync(tokenDraft)
      setTokenDraft('')
      setEditingToken(false)
    } catch (error) {
      setActionError(configErrorMessage(error, t('settings.errSaveSetting'), t))
    } finally {
      setSavingELToken(false)
    }
  }

  const thresholdControlsDisabled = loadingConfig || !config || savingThreshold
  const unloadAfterStop = config?.unload_models_after_stop ?? false
  const preloadOnStart = config?.preload_on_start ?? false
  const blocklistEnabled = config?.blocklist_enabled ?? false
  const storage = storageQuery.data ?? null

  const renderModelCards = (
    kind: ProviderKind,
    models: ModelDef[],
    provider: ApiProviderStatus | undefined,
    selectedId: string,
  ) =>
    models.map((model) => {
      const cardState = providerCardState(provider, model.id)
      const isSelectedCard = selectedId === model.id
      return (
        <ModelCard
          key={model.id}
          kind={kind}
          model={model}
          state={cardState}
          selected={isSelectedCard}
          disabled={loadingConfig || savingProvider !== null || modelAction !== null}
          buttonLabel={
            savingProvider === kind
              ? t('settings.saving')
              : isSelectedCard
                ? t('settings.selected')
                : t('settings.select')
          }
          onSelect={() => void handleProviderSelect(kind, model.id)}
          lifecycleLabel={lifecycleLabel(kind, cardState)}
          lifecycleDisabled={
            loadingConfig ||
            savingProvider !== null ||
            modelAction !== null ||
            cardState === 'LOADING'
          }
          onLifecycle={() => void handleModelLifecycle(kind)}
          errorMessage={isSelectedCard ? provider?.error ?? null : null}
        />
      )
    })

  return (
    <div style={stS.root}>
      <div style={stS.sidenav}>
        <div style={stS.sidenavTitle}>{t('settings.title')}</div>
        {sections.map((section) => (
          <button
            key={section.id}
            data-testid={`settings-tab-${section.id}`}
            onClick={() => setActive(section.id)}
            style={{
              ...stS.sidenavItem,
              ...(active === section.id ? stS.sidenavActive : {}),
            }}
          >
            {active === section.id && <div style={stS.sidenavLine} />}
            {section.label}
          </button>
        ))}
      </div>

      <div style={stS.content}>
        {(loadingConfig || configError) && (
          <div
            style={{
              ...stS.statusCard,
              ...(configError ? stS.statusCardError : {}),
            }}
          >
            {loadingConfig
              ? t('settings.loadingConfig')
              : configError}
          </div>
        )}

        {active === 'providers' && (
          <>
            <SectionTitle>{t('settings.asrSection')}</SectionTitle>
            <div style={stS.modelGrid}>
              {renderModelCards('asr', asrModels, asrProvider, selectedAsrModel)}
            </div>

            {selectedAsrModel === 'elevenlabs-scribe' && (
              <div style={{ marginTop: 14 }}>
                <div style={stS.settingRow}>
                  <div style={{ flex: 1 }}>
                    <div style={stS.settingName}>
                      {t('settings.elevenlabsTokenLabel')}
                    </div>
                    <div style={stS.settingDesc}>
                      {t('settings.elevenlabsTokenDesc')}
                    </div>
                  </div>
                  <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                    {editingToken ? (
                      <>
                        <input
                          data-testid="elevenlabs-token-input"
                          type="password"
                          value={tokenDraft}
                          onChange={(e) => setTokenDraft(e.target.value)}
                          placeholder="sk-…"
                          disabled={savingELToken}
                          onKeyDown={(e) => {
                            if (e.key === 'Enter') void commitElevenLabsToken()
                            if (e.key === 'Escape') {
                              setEditingToken(false)
                              setTokenDraft('')
                            }
                          }}
                          style={{
                            background: 'var(--surface2)',
                            border: '1px solid var(--border)',
                            borderRadius: 6,
                            padding: '5px 10px',
                            fontSize: 12,
                            color: 'var(--text)',
                            fontFamily: 'var(--mono)',
                            width: 220,
                          }}
                        />
                        <button
                          data-testid="elevenlabs-token-save"
                          onClick={() => void commitElevenLabsToken()}
                          disabled={savingELToken || tokenDraft.trim() === ''}
                          style={{
                            ...stS.modelBtn,
                            ...stS.modelBtnIdle,
                            ...(savingELToken || tokenDraft.trim() === ''
                              ? stS.modelBtnDisabled : {}),
                          }}
                        >
                          {savingELToken ? t('settings.saving') : t('common.save')}
                        </button>
                      </>
                    ) : (
                      <>
                        <span
                          style={{
                            fontSize: 12.5,
                            fontFamily: 'var(--mono)',
                            color: 'var(--text-muted)',
                          }}
                        >
                          {config?.elevenlabs_api_token_masked ?? 'not set'}
                        </span>
                        <button
                          data-testid="elevenlabs-token-edit"
                          onClick={() => {
                            setEditingToken(true)
                            setTokenDraft('')
                          }}
                          disabled={savingELToken}
                          style={{
                            ...stS.modelBtn,
                            ...stS.modelBtnIdle,
                          }}
                        >
                          {t('settings.elevenlabsTokenSet')}
                        </button>
                      </>
                    )}
                  </div>
                </div>
              </div>
            )}

            <SectionTitle mt={28}>{t('settings.embedSection')}</SectionTitle>
            <div style={stS.modelGrid}>
              {renderModelCards(
                'embedding',
                embeddingModels,
                embeddingProvider,
                selectedEmbeddingModel,
              )}
            </div>

            <SectionTitle mt={28}>{t('settings.diarSection')}</SectionTitle>
            <div style={stS.modelGrid}>
              {renderModelCards(
                'diarization',
                diarizationModels,
                diarizationProvider,
                selectedDiarizationModel,
              )}
            </div>
          </>
        )}

        {active === 'speech' && (
          <>
            <SectionTitle>{t('settings.pipelineSection')}</SectionTitle>

            <div style={stS.settingRow}>
              <div style={{ flex: 1 }}>
                <div style={stS.settingName}>{t('settings.vadOnsetLabel')}</div>
                <div style={stS.settingDesc}>{t('settings.vadOnsetDesc')}</div>
              </div>
              <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                <input
                  type="range"
                  min={20} max={100}
                  value={Math.round(vadOnset * 100)}
                  disabled={savingPipeline}
                  onChange={(e) => setVadOnset(Number(e.target.value) / 100)}
                  onPointerUp={() => commitPipeline({ vad_threshold: vadOnset })}
                  style={{ width: 140, accentColor: 'var(--accent)' }}
                />
                <span style={stS.paramValue}>{vadOnset.toFixed(2)}</span>
              </div>
            </div>

            <div style={stS.settingRow}>
              <div style={{ flex: 1 }}>
                <div style={stS.settingName}>{t('settings.vadOffsetLabel')}</div>
                <div style={stS.settingDesc}>{t('settings.vadOffsetDesc')}</div>
              </div>
              <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                <input
                  type="range"
                  min={1} max={100}
                  value={Math.round(vadOffset * 100)}
                  disabled={savingPipeline}
                  onChange={(e) => setVadOffset(Number(e.target.value) / 100)}
                  onPointerUp={() => commitPipeline({ vad_negative_threshold: vadOffset })}
                  style={{ width: 140, accentColor: 'var(--accent)' }}
                />
                <span style={stS.paramValue}>{vadOffset.toFixed(2)}</span>
              </div>
            </div>

            <Divider />

            <div style={stS.settingRow}>
              <div style={{ flex: 1 }}>
                <div style={stS.settingName}>{t('settings.vadMinSilenceLabel')}</div>
                <div style={stS.settingDesc}>{t('settings.vadMinSilenceDesc')}</div>
              </div>
              <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                <input
                  type="range"
                  min={100} max={800}
                  value={vadMinSilence}
                  disabled={savingPipeline}
                  onChange={(e) => setVadMinSilence(Number(e.target.value))}
                  onPointerUp={() => commitPipeline({ vad_min_silence_ms: vadMinSilence })}
                  style={{ width: 120, accentColor: 'var(--accent)' }}
                />
                <span style={stS.paramValue}>{vadMinSilence} ms</span>
              </div>
            </div>

            <div style={stS.settingRow}>
              <div style={{ flex: 1 }}>
                <div style={stS.settingName}>{t('settings.vadPadPreLabel')}</div>
                <div style={stS.settingDesc}>{t('settings.vadPadPreDesc')}</div>
              </div>
              <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                <input
                  type="range"
                  min={50} max={600}
                  value={vadPadPre}
                  disabled={savingPipeline}
                  onChange={(e) => setVadPadPre(Number(e.target.value))}
                  onPointerUp={() => commitPipeline({ vad_speech_pad_pre_ms: vadPadPre })}
                  style={{ width: 120, accentColor: 'var(--accent)' }}
                />
                <span style={stS.paramValue}>{vadPadPre} ms</span>
              </div>
            </div>

            <div style={stS.settingRow}>
              <div style={{ flex: 1 }}>
                <div style={stS.settingName}>{t('settings.vadPadPostLabel')}</div>
                <div style={stS.settingDesc}>{t('settings.vadPadPostDesc')}</div>
              </div>
              <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                <input
                  type="range"
                  min={50} max={800}
                  value={vadPadPost}
                  disabled={savingPipeline}
                  onChange={(e) => setVadPadPost(Number(e.target.value))}
                  onPointerUp={() => commitPipeline({ vad_speech_pad_post_ms: vadPadPost })}
                  style={{ width: 120, accentColor: 'var(--accent)' }}
                />
                <span style={stS.paramValue}>{vadPadPost} ms</span>
              </div>
            </div>

            <Divider />

            <div style={stS.settingRow}>
              <div style={{ flex: 1 }}>
                <div style={stS.settingName}>{t('settings.vadMinUttLabel')}</div>
                <div style={stS.settingDesc}>{t('settings.vadMinUttDesc')}</div>
              </div>
              <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                <input
                  type="range"
                  min={50} max={1000}
                  value={vadMinUtt}
                  disabled={savingPipeline}
                  onChange={(e) => setVadMinUtt(Number(e.target.value))}
                  onPointerUp={() => commitPipeline({ vad_min_utterance_ms: vadMinUtt })}
                  style={{ width: 120, accentColor: 'var(--accent)' }}
                />
                <span style={stS.paramValue}>{vadMinUtt} ms</span>
              </div>
            </div>

            <div style={stS.settingRow}>
              <div style={{ flex: 1 }}>
                <div style={stS.settingName}>{t('settings.vadMaxUttLabel')}</div>
                <div style={stS.settingDesc}>{t('settings.vadMaxUttDesc')}</div>
              </div>
              <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                <input
                  type="range"
                  min={3_000} max={60_000} step={1_000}
                  value={vadMaxUtt}
                  disabled={savingPipeline}
                  onChange={(e) => setVadMaxUtt(Number(e.target.value))}
                  onPointerUp={() => commitPipeline({ vad_max_utterance_ms: vadMaxUtt })}
                  style={{ width: 120, accentColor: 'var(--accent)' }}
                />
                <span style={stS.paramValue}>{(vadMaxUtt / 1000).toFixed(0)} s</span>
              </div>
            </div>

            <div style={stS.inlineHint}>
              {savingPipeline ? t('settings.saving') : t('settings.vadRequiresRestart')}
            </div>
          </>
        )}

        {active === 'transcription' && (
          <>
            <SectionTitle>{t('settings.asrQualitySection')}</SectionTitle>

            <div style={stS.settingRow}>
              <div style={{ flex: 1 }}>
                <div style={stS.settingName}>{t('settings.asrNoSpeechLabel')}</div>
                <div style={stS.settingDesc}>{t('settings.asrNoSpeechDesc')}</div>
              </div>
              <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                <input
                  type="range"
                  min={1} max={100}
                  value={Math.round(asrNoSpeech * 100)}
                  disabled={savingPipeline}
                  onChange={(e) => setAsrNoSpeech(Number(e.target.value) / 100)}
                  onPointerUp={() => commitPipeline({ asr_no_speech_threshold: asrNoSpeech })}
                  style={{ width: 120, accentColor: 'var(--accent)' }}
                />
                <span style={stS.paramValue}>{asrNoSpeech.toFixed(2)}</span>
              </div>
            </div>

            <div style={stS.settingRow}>
              <div style={{ flex: 1 }}>
                <div style={stS.settingName}>{t('settings.asrCompressionLabel')}</div>
                <div style={stS.settingDesc}>{t('settings.asrCompressionDesc')}</div>
              </div>
              <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                <input
                  type="range"
                  min={100} max={500}
                  value={Math.round(asrCompression * 100)}
                  disabled={savingPipeline}
                  onChange={(e) => setAsrCompression(Number(e.target.value) / 100)}
                  onPointerUp={() => commitPipeline({ asr_compression_ratio_threshold: asrCompression })}
                  style={{ width: 120, accentColor: 'var(--amber)' }}
                />
                <span style={stS.paramValue}>{asrCompression.toFixed(1)}</span>
              </div>
            </div>

            <div style={stS.settingRow}>
              <div style={{ flex: 1 }}>
                <div style={stS.settingName}>{t('settings.asrRepPenaltyLabel')}</div>
                <div style={stS.settingDesc}>{t('settings.asrRepPenaltyDesc')}</div>
              </div>
              <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                <input
                  type="range"
                  min={100} max={200}
                  value={Math.round(asrRepPenalty * 100)}
                  disabled={savingPipeline}
                  onChange={(e) => setAsrRepPenalty(Number(e.target.value) / 100)}
                  onPointerUp={() => commitPipeline({ asr_repetition_penalty: asrRepPenalty })}
                  style={{ width: 120, accentColor: 'var(--amber)' }}
                />
                <span style={stS.paramValue}>{asrRepPenalty.toFixed(2)}</span>
              </div>
            </div>

            <div style={stS.settingRow}>
              <div style={{ flex: 1 }}>
                <div style={stS.settingName}>{t('settings.asrNgramLabel')}</div>
                <div style={stS.settingDesc}>{t('settings.asrNgramDesc')}</div>
              </div>
              <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                <input
                  type="range"
                  min={0} max={10}
                  value={asrNgram}
                  disabled={savingPipeline}
                  onChange={(e) => setAsrNgram(Number(e.target.value))}
                  onPointerUp={() => commitPipeline({ asr_no_repeat_ngram_size: asrNgram })}
                  style={{ width: 100, accentColor: 'var(--amber)' }}
                />
                <span style={{ ...stS.paramValue, width: 24 }}>{asrNgram}</span>
              </div>
            </div>

            <Divider />

            <SectionTitle mt={20}>{t('settings.textCleanupSection')}</SectionTitle>

            <div style={stS.settingRow}>
              <div style={{ flex: 1 }}>
                <div style={stS.settingName}>
                  {t('settings.blocklistEnabled')}
                </div>
                <div style={stS.settingDesc}>
                  {t('settings.blocklistEnabledDesc')}
                </div>
              </div>
              <Toggle
                dataTestId="blocklist-toggle"
                on={blocklistEnabled}
                onChange={(next) => void commitBlocklistEnabled(next)}
                disabled={loadingConfig || !config || savingBlocklist}
              />
            </div>

            <div style={stS.settingRow}>
              <div style={{ flex: 1 }}>
                <div style={stS.settingName}>{t('settings.itnEnabledLabel')}</div>
                <div style={stS.settingDesc}>{t('settings.itnEnabledDesc')}</div>
              </div>
              <Toggle
                dataTestId="itn-toggle"
                on={itnEnabled}
                onChange={(next) => {
                  setItnEnabled(next)
                  void commitPipeline({ itn_enabled: next })
                }}
                disabled={loadingConfig || !config || savingPipeline}
              />
            </div>

            <div style={stS.settingRow}>
              <div style={{ flex: 1 }}>
                <div style={stS.settingName}>{t('settings.itnMapsLabel')}</div>
                <div style={stS.settingDesc}>{t('settings.itnMapsDesc')}</div>
              </div>
              <div style={{ width: 260 }}>
                <MultiSelect
                  options={itnMapOptions}
                  selected={itnSelectedMaps}
                  onChange={(vals) => {
                    setItnSelectedMaps(vals)
                    void commitPipeline({ itn_selected_maps: vals })
                  }}
                  placeholder={t('settings.itnMapsPlaceholder')}
                  disabled={!itnEnabled || savingPipeline}
                  dataTestId="itn-maps"
                />
              </div>
            </div>

            <div style={stS.inlineHint}>
              {savingPipeline ? t('settings.saving') : t('settings.itnMapsHint')}
            </div>

            <Divider />

            <SectionTitle mt={20}>{t('settings.draftSection')}</SectionTitle>

            <div style={stS.settingRow}>
              <div style={{ flex: 1 }}>
                <div style={stS.settingName}>{t('settings.draftEnabledLabel')}</div>
                <div style={stS.settingDesc}>{t('settings.draftEnabledDesc')}</div>
              </div>
              <Toggle
                dataTestId="draft-toggle"
                on={draftEnabled}
                onChange={(next) => {
                  setDraftEnabled(next)
                  void commitPipeline({ draft_enabled: next })
                }}
                disabled={loadingConfig || !config || savingPipeline}
              />
            </div>

            <Divider />

            <SectionTitle mt={20}>{t('settings.languageFiltering')}</SectionTitle>

            <div style={stS.settingRow}>
              <div style={{ flex: 1 }}>
                <div style={stS.settingName}>{t('settings.langAllowlistEnabledLabel')}</div>
                <div style={stS.settingDesc}>{t('settings.langAllowlistEnabledDesc')}</div>
              </div>
              <Toggle
                dataTestId="lang-allowlist-toggle"
                on={langAllowlistEnabled}
                onChange={(next) => {
                  setLangAllowlistEnabled(next)
                  void commitPipeline({ language_allowlist_enabled: next })
                }}
                disabled={loadingConfig || !config || savingPipeline}
              />
            </div>

            <div style={stS.settingRow}>
              <div style={{ flex: 1 }}>
                <div style={stS.settingName}>{t('settings.languageAllowlist')}</div>
                <div style={stS.settingDesc}>{t('settings.langAllowlistDesc')}</div>
              </div>
              <div style={{ width: 260 }}>
                <MultiSelect
                  options={LANGUAGE_OPTIONS}
                  selected={langAllowlist}
                  onChange={(vals) => {
                    setLangAllowlist(vals)
                    void commitPipeline({ language_allowlist: vals.join(',') })
                  }}
                  placeholder={t('settings.langAllowlistPlaceholder')}
                  disabled={!langAllowlistEnabled || savingPipeline}
                  dataTestId="lang-allowlist"
                />
              </div>
            </div>

            <div style={stS.settingRow}>
              <div style={{ flex: 1 }}>
                <div style={stS.settingName}>{t('settings.langConfidenceThresholdLabel')}</div>
                <div style={stS.settingDesc}>{t('settings.langConfidenceThresholdDesc')}</div>
              </div>
              <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                <input
                  type="range"
                  min={1} max={100}
                  value={Math.round(langConfidenceThreshold * 100)}
                  disabled={!langAllowlistEnabled || savingPipeline}
                  onChange={(e) => setLangConfidenceThreshold(Number(e.target.value) / 100)}
                  onPointerUp={() => commitPipeline({ language_confidence_threshold: langConfidenceThreshold })}
                  style={{ width: 120, accentColor: 'var(--accent)' }}
                />
                <span style={stS.paramValue}>{langConfidenceThreshold.toFixed(2)}</span>
              </div>
            </div>

            <div style={stS.inlineHint}>
              {savingPipeline ? t('settings.saving') : t('settings.langAllowlistHint')}
            </div>

            <div style={stS.inlineHint}>
              {savingPipeline ? t('settings.saving') : t('settings.asrParamsHint')}
            </div>
          </>
        )}

        {active === 'speakers' && (
          <>
            <SectionTitle>{t('settings.speakerSection')}</SectionTitle>
            <div style={stS.settingRow}>
              <div style={{ flex: 1 }}>
                <div style={stS.settingName}>{t('settings.micSelfContactLabel')}</div>
                <div style={stS.settingDesc}>{t('settings.micSelfContactDesc')}</div>
              </div>
              <div style={{ width: 220 }}>
                <ContactPicker
                  selectedId={micSelfContactId}
                  onChange={(id) => {
                    setMicSelfContactId(id)
                    void commitPipeline({ mic_self_contact_id: id })
                  }}
                  placeholder={t('settings.micSelfContactPlaceholder')}
                  disabled={loadingConfig || !config || savingPipeline}
                  dataTestId="mic-self-contact"
                />
              </div>
            </div>

            <Divider />

            <div style={{ paddingTop: 12 }}>
              <div style={stS.settingName}>{t('settings.thresholdLabel')}</div>
              <div style={stS.settingDesc}>
                {t('settings.thresholdDesc')}
              </div>
              <div
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 12,
                  marginTop: 14,
                }}
              >
                <span
                  style={{
                    fontSize: 11,
                    color: 'var(--text-dim)',
                    fontFamily: 'var(--mono)',
                    flexShrink: 0,
                  }}
                >
                  0.00
                </span>
                <input
                  data-testid="threshold-slider"
                  type="range"
                  min={0}
                  max={100}
                  value={Math.round(threshold * 100)}
                  disabled={thresholdControlsDisabled}
                  onChange={(e) =>
                    setThresholdValue(Number(e.target.value) / 100)
                  }
                  onPointerUp={() => void commitThreshold(threshold)}
                  onBlur={() => void commitThreshold(threshold)}
                  onKeyUp={(e) => {
                    if (
                      [
                        'ArrowLeft',
                        'ArrowRight',
                        'ArrowUp',
                        'ArrowDown',
                        'Home',
                        'End',
                        'PageUp',
                        'PageDown',
                      ].includes(e.key)
                    ) {
                      void commitThreshold(Number(e.currentTarget.value) / 100)
                    }
                  }}
                  style={{
                    flex: 1,
                    accentColor: 'var(--accent)',
                    cursor: thresholdControlsDisabled ? 'default' : 'pointer',
                  }}
                />
                <span
                  style={{
                    fontSize: 11,
                    color: 'var(--text-dim)',
                    fontFamily: 'var(--mono)',
                    flexShrink: 0,
                  }}
                >
                  1.00
                </span>
                <span
                  style={{
                    fontSize: 15,
                    fontWeight: 700,
                    fontFamily: 'var(--mono)',
                    color: thresholdColor,
                    width: 40,
                    textAlign: 'right',
                  }}
                >
                  {threshold.toFixed(2)}
                </span>
              </div>
              <div style={stS.inlineHint}>
                {savingThreshold ? t('settings.saving') : t('settings.thresholdHint')}
              </div>
            </div>
            <div style={stS.inlineHint}>
              {savingPipeline ? t('settings.saving') : t('settings.speakerHint')}
            </div>
          </>
        )}

        {active === 'runtime' && (
          <>
            <SectionTitle>{t('settings.runtimeBehavior')}</SectionTitle>
            <div style={stS.settingRow}>
              <div style={{ flex: 1 }}>
                <div style={stS.settingName}>
                  {t('settings.unloadAfterStop')}
                </div>
                <div style={stS.settingDesc}>
                  {t('settings.unloadAfterStopDesc')}
                </div>
              </div>
              <Toggle
                dataTestId="unload-toggle"
                on={unloadAfterStop}
                onChange={(next) => void commitUnloadAfterStop(next)}
                disabled={loadingConfig || !config || savingUnload}
              />
            </div>
            <div style={stS.settingRow}>
              <div style={{ flex: 1 }}>
                <div style={stS.settingName}>
                  {t('settings.preloadOnStart')}
                </div>
                <div style={stS.settingDesc}>
                  {t('settings.preloadOnStartDesc')}
                </div>
              </div>
              <Toggle
                dataTestId="preload-toggle"
                on={preloadOnStart}
                onChange={(next) => void commitPreloadOnStart(next)}
                disabled={loadingConfig || !config || savingPreload}
              />
            </div>
          </>
        )}

        {active === 'storage' && (
          <>
            <SectionTitle>{t('settings.storage')}</SectionTitle>
            <div data-testid="storage-info" style={stS.infoBox}>
              {(
                [
                  [
                    t('settings.dbPath'),
                    storage?.db_path ||
                      (storageQuery.isLoading ? t('common.loading') : '—'),
                  ],
                  [
                    t('settings.dbSize'),
                    storage
                      ? storage.exists
                        ? formatBytes(storage.db_size_bytes)
                        : t('settings.dbMissing')
                      : storageQuery.isLoading
                        ? t('common.loading')
                        : '—',
                  ],
                ] as const
              ).map(([key, value]) => (
                <div
                  key={key}
                  style={{
                    display: 'flex',
                    justifyContent: 'space-between',
                    gap: 12,
                    marginBottom: 6,
                  }}
                >
                  <span style={{ fontSize: 12.5, color: 'var(--text-muted)' }}>
                    {key}
                  </span>
                  <span
                    style={{
                      fontSize: 12,
                      fontFamily: 'var(--mono)',
                      color: 'var(--text-muted)',
                      textAlign: 'right',
                      wordBreak: 'break-all',
                    }}
                  >
                    {value}
                  </span>
                </div>
              ))}
            </div>
          </>
        )}

        {active === 'appearance' && (
          <>
            <SectionTitle>{t('settings.appearance')}</SectionTitle>
            <div style={stS.settingRow}>
              <div style={stS.settingName}>{t('settings.theme')}</div>
              <div style={{ display: 'flex', gap: 5 }}>
                {(
                  [
                    ['light', t('settings.themeLight')],
                    ['dark', t('settings.themeDark')],
                  ] as const
                ).map(([value, label]) => {
                  const isActive = theme === value
                  return (
                    <button
                      key={value}
                      data-testid={`theme-toggle-${value}`}
                      onClick={() => {
                        setThemeState(value)
                        document.documentElement.setAttribute('data-theme', value)
                        try { localStorage.setItem('vd-theme', value) } catch {}
                      }}
                      style={{
                        ...stS.segBtn,
                        ...(isActive ? stS.segBtnActive : {}),
                      }}
                    >
                      {label}
                    </button>
                  )
                })}
              </div>
            </div>
            <div style={stS.settingRow}>
              <div style={stS.settingName}>{t('settings.uiLang')}</div>
              <div style={{ display: 'flex', gap: 5 }}>
                {(
                  [
                    ['uk', t('settings.languageUkrainian')],
                    ['en', t('settings.languageEnglish')],
                  ] as const
                ).map(([code, label]) => {
                  const isActive = (i18nInstance.resolvedLanguage ?? i18nInstance.language ?? 'uk').startsWith(code)
                  return (
                    <button
                      key={code}
                      data-testid={`lang-select-${code}`}
                      onClick={() => void i18nInstance.changeLanguage(code)}
                      style={{
                        ...stS.segBtn,
                        ...(isActive ? stS.segBtnActive : {}),
                      }}
                    >
                      {label}
                    </button>
                  )
                })}
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  )
}

const stS: Record<string, CSSProperties> = {
  root: {
    display: 'flex',
    height: '100vh',
    background: 'var(--bg)',
    fontFamily: 'var(--sans)',
  },
  sidenav: {
    width: 190,
    borderRight: '1px solid var(--border)',
    padding: '18px 0',
    flexShrink: 0,
    background: 'var(--surface)',
  },
  sidenavTitle: {
    fontSize: 14.5,
    fontWeight: 600,
    color: 'var(--text)',
    padding: '0 18px 14px',
  },
  sidenavItem: {
    width: '100%',
    background: 'none',
    border: 'none',
    textAlign: 'left',
    padding: '8px 18px',
    fontSize: 13,
    color: 'var(--text-muted)',
    cursor: 'pointer',
    position: 'relative',
    borderRadius: 0,
  },
  sidenavActive: { color: 'var(--text)', background: 'rgba(38,37,30,0.05)' },
  sidenavLine: {
    position: 'absolute',
    left: 0,
    top: '20%',
    bottom: '20%',
    width: 2,
    background: 'var(--accent)',
    borderRadius: 1,
  },
  content: { flex: 1, overflowY: 'auto', padding: '26px 30px' },
  statusCard: {
    background: 'var(--surface)',
    border: '1px solid var(--border)',
    borderRadius: 8,
    padding: '10px 14px',
    marginBottom: 18,
    fontSize: 12.5,
    color: 'var(--text-muted)',
    fontFamily: 'var(--mono)',
  },
  statusCardError: {
    border: '1px solid rgba(207,45,86,0.22)',
    color: 'var(--record)',
    background: 'rgba(207,45,86,0.05)',
  },
  modelGrid: { display: 'flex', flexDirection: 'column', gap: 7 },
  modelCard: {
    background: 'var(--surface)',
    border: '1px solid var(--border)',
    borderRadius: 8,
    padding: '12px 14px',
    cursor: 'pointer',
    transition: 'border-color 0.12s',
    position: 'relative',
  },
  modelCardSel: {
    border: '1px solid rgba(245,78,0,0.4)',
    background: 'rgba(245,78,0,0.04)',
  },
  modelCardDisabled: {
    cursor: 'default',
  },
  modelCheck: {
    position: 'absolute',
    top: 13,
    right: 14,
    color: 'var(--accent)',
    fontSize: 14,
    fontWeight: 700,
    lineHeight: 1,
  },
  modelTop: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 4,
    gap: 12,
  },
  modelName: {
    fontSize: 13.5,
    fontWeight: 500,
    color: 'var(--text)',
    fontFamily: 'var(--mono)',
  },
  modelMeta: {
    display: 'flex',
    gap: 8,
    fontSize: 11.5,
    color: 'var(--text-dim)',
    fontFamily: 'var(--mono)',
    marginBottom: 8,
    flexWrap: 'wrap',
  },
  modelError: {
    fontSize: 11.5,
    color: 'var(--record)',
    fontFamily: 'var(--mono)',
    background: 'rgba(207,45,86,0.06)',
    border: '1px solid rgba(207,45,86,0.18)',
    borderRadius: 6,
    padding: '6px 8px',
    marginBottom: 8,
    whiteSpace: 'pre-wrap',
    wordBreak: 'break-word',
  },
  modelActions: {
    display: 'flex',
    gap: 8,
    flexWrap: 'wrap',
  },
  modelBtn: {
    border: '1px solid',
    borderRadius: 9999,
    padding: '4px 12px',
    fontSize: 12,
    cursor: 'pointer',
    fontWeight: 500,
  },
  modelBtnIdle: {
    color: 'var(--accent)',
    borderColor: 'rgba(245,78,0,0.25)',
    background: 'var(--accent-dim)',
  },
  modelBtnSelected: {
    color: 'var(--text-muted)',
    borderColor: 'var(--border)',
    background: 'var(--surface2)',
  },
  modelBtnDisabled: {
    cursor: 'default',
    opacity: 0.75,
  },
  settingRow: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: 16,
    padding: '12px 0',
  },
  settingName: {
    fontSize: 13.5,
    fontWeight: 500,
    color: 'var(--text)',
    marginBottom: 2,
  },
  settingDesc: { fontSize: 12, color: 'var(--text-muted)', lineHeight: 1.5 },
  inlineHint: {
    fontSize: 11,
    color: 'var(--text-dim)',
    fontFamily: 'var(--mono)',
    marginTop: 9,
  },
  paramValue: {
    fontSize: 13,
    fontWeight: 500,
    fontFamily: 'var(--mono)',
    color: 'var(--text)',
    width: 56,
    textAlign: 'right' as const,
    flexShrink: 0,
  },
  infoBox: {
    background: 'var(--surface)',
    border: '1px solid var(--border)',
    borderRadius: 7,
    padding: '12px 14px',
    marginBottom: 12,
  },
  segBtn: {
    background: 'var(--surface2)',
    border: '1px solid var(--border)',
    color: 'var(--text-muted)',
    borderRadius: 6,
    padding: '5px 11px',
    fontSize: 12,
    cursor: 'pointer',
    fontFamily: 'var(--mono)',
  },
  segBtnActive: {
    background: 'rgba(245,78,0,0.1)',
    borderColor: 'rgba(245,78,0,0.35)',
    color: 'var(--accent)',
  },
}
