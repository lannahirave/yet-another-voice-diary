import { useEffect, useMemo, useRef, useState } from 'react'
import type { CSSProperties, ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { subscribeModelProgress } from '../api/models'
import {
  useConfigQuery,
  useModelLifecycleMutation,
  usePreloadOnStartMutation,
  useSelectProviderMutation,
  useSetThresholdMutation,
  useStorageInfoQuery,
  useUnloadAfterStopMutation,
} from '../query/config'
import type { ApiProviderStatus } from '../types/api'
import { Toggle } from './shared/Toggle'

type ModelState =
  | 'LOADED'
  | 'UNLOADED'
  | 'LOADING'
  | 'NOT_DOWNLOADED'
  | 'AVAILABLE'
  | 'ERROR'

type ProviderKind = 'asr' | 'embedding' | 'diarization'
type SectionId = 'providers' | 'memory' | 'storage' | 'general'

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
  progress?: number
  errorMessage?: string | null
}

const ASR_MODELS: ModelDef[] = [
  {
    id: 'tiny',
    name: 'whisper tiny',
    size: '~39 MB',
    speed: '~32× realtime',
    quality: 'settings.qualityAcceptable',
  },
  {
    id: 'medium',
    name: 'whisper medium',
    size: '~1.5 GB',
    speed: '~8× realtime',
    quality: 'settings.qualityGood',
  },
  {
    id: 'large-v3-turbo',
    name: 'whisper large-v3-turbo',
    size: '~1.6 GB',
    speed: '~8× realtime',
    quality: 'settings.qualityRecommended',
  },
]

const EMBED_MODELS: ModelDef[] = [
  {
    id: 'ecapa',
    name: 'ECAPA-TDNN',
    size: '~85 MB',
    speed: 'settings.speedFast',
    quality: 'settings.qualityRecommendedM',
  },
  {
    id: 'wavlm',
    name: 'WavLM Large',
    size: '~1.3 GB',
    speed: '—',
    quality: 'settings.qualityAccurate',
  },
]

const DIAR_MODELS: ModelDef[] = [
  {
    id: 'pyannote',
    name: 'PyAnnote 3.1',
    size: '~270 MB',
    speed: 'settings.speedRealtime',
    quality: 'settings.qualityRecommended',
  },
  {
    id: 'sortformer-v2.1',
    name: 'NVIDIA Streaming Sortformer 4spk v2.1',
    size: '—',
    speed: 'settings.speedRealtime',
    quality: 'settings.qualityAlternative',
  },
]

const sectionsBase: Array<{ id: SectionId; labelKey: string }> = [
  { id: 'providers', labelKey: 'settings.tabProviders' },
  { id: 'memory', labelKey: 'settings.tabMemory' },
  { id: 'storage', labelKey: 'settings.tabStorage' },
  { id: 'general', labelKey: 'settings.tabGeneral' },
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
  progress,
  errorMessage,
}: ModelCardProps) {
  const { t } = useTranslation()
  const buttonDisabled = disabled || selected
  const baseLabel = t(STATE_LABEL_KEYS[state])
  const stateLabel =
    state === 'LOADING' && typeof progress === 'number'
      ? `${baseLabel} ${Math.round(progress * 100)}%`
      : baseLabel
  const speedLabel = t(model.speed, { defaultValue: model.speed })
  const qualityLabel = t(model.quality, { defaultValue: model.quality })

  const handleSelect = () => {
    if (buttonDisabled) return
    onSelect()
  }

  return (
    <div
      onClick={handleSelect}
      style={{
        ...stS.modelCard,
        ...(selected ? stS.modelCardSel : {}),
        ...(buttonDisabled ? stS.modelCardDisabled : {}),
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
        <span>{speedLabel}</span>
        <span style={{ color: 'var(--border-str)' }}>·</span>
        <span style={{ color: 'var(--text-muted)' }}>{qualityLabel}</span>
      </div>
      {state === 'LOADING' && typeof progress === 'number' && (
        <div style={stS.progressTrack}>
          <div
            style={{
              ...stS.progressFill,
              width: `${Math.max(2, Math.round(progress * 100))}%`,
            }}
          />
        </div>
      )}
      {state === 'ERROR' && errorMessage && (
        <div style={stS.modelError}>{errorMessage}</div>
      )}
      <div style={stS.modelActions}>
        <button
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

const PROVIDER_KINDS: ProviderKind[] = ['asr', 'embedding', 'diarization']

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
  const [modelAction, setModelAction] = useState<ProviderKind | null>(null)
  const [progressByKind, setProgressByKind] = useState<Record<string, number>>({})

  const configQuery = useConfigQuery()
  const storageQuery = useStorageInfoQuery()
  const selectProviderMutation = useSelectProviderMutation()
  const setThresholdMutation = useSetThresholdMutation()
  const unloadAfterStopMutation = useUnloadAfterStopMutation()
  const preloadOnStartMutation = usePreloadOnStartMutation()
  const modelLifecycleMutation = useModelLifecycleMutation()

  const config = configQuery.data ?? null
  const loadingConfig = configQuery.isLoading
  const configError = actionError
    ?? (configQuery.error ? configErrorMessage(configQuery.error, t('settings.errLoadConfig'), t) : null)

  useEffect(() => {
    if (config) {
      setThresholdValue(config.speaker_identification_threshold)
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

  const refetchConfig = configQuery.refetch
  const loadingKinds = useMemo(
    () => PROVIDER_KINDS.filter((k) => providers[k]?.state === 'LOADING'),
    [providers],
  )

  // Subscribe to SSE progress only while at least one provider is LOADING.
  // Each subscription closes itself when the stream emits its final snapshot.
  const activeStreams = useRef<Set<string>>(new Set())
  useEffect(() => {
    const disposers: Array<() => void> = []
    for (const kind of loadingKinds) {
      if (activeStreams.current.has(kind)) continue
      activeStreams.current.add(kind)
      const dispose = subscribeModelProgress(
        kind,
        (event) => {
          setProgressByKind((prev) => ({ ...prev, [kind]: event.progress }))
          if (event.state === 'LOADED' || event.state === 'ERROR' || event.state === 'UNLOADED') {
            activeStreams.current.delete(kind)
            void refetchConfig()
          }
        },
        () => {
          activeStreams.current.delete(kind)
          void refetchConfig()
        },
      )
      disposers.push(dispose)
    }
    return () => {
      for (const dispose of disposers) dispose()
    }
  }, [loadingKinds, refetchConfig])

  const asrProvider = providers.asr
  const embeddingProvider = providers.embedding
  const diarizationProvider = providers.diarization

  const asrModels = useMemo(
    () => withCurrentFallback(ASR_MODELS, asrProvider),
    [asrProvider],
  )
  const embeddingModels = useMemo(
    () => withCurrentFallback(EMBED_MODELS, embeddingProvider),
    [embeddingProvider],
  )
  const diarizationModels = useMemo(
    () => withCurrentFallback(DIAR_MODELS, diarizationProvider),
    [diarizationProvider],
  )

  const selectedAsrModel = asrProvider?.model_id ?? 'large-v3-turbo'
  const selectedEmbeddingModel = embeddingProvider?.model_id ?? 'ecapa'
  const selectedDiarizationModel = diarizationProvider?.model_id ?? 'pyannote'
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
    if (state === 'LOADING') {
      const pct = progressByKind[kind]
      return typeof pct === 'number'
        ? `${t('settings.btnLoading')} ${Math.round(pct * 100)}%`
        : t('settings.btnLoading')
    }
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

  const thresholdControlsDisabled = loadingConfig || !config || savingThreshold
  const unloadAfterStop = config?.unload_models_after_stop ?? false
  const preloadOnStart = config?.preload_on_start ?? false
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
      const showProgress = isSelectedCard && cardState === 'LOADING'
      return (
        <ModelCard
          key={model.id}
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
          progress={showProgress ? progressByKind[kind] ?? 0.05 : undefined}
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

        {active === 'memory' && (
          <>
            <SectionTitle>{t('settings.memoryBehavior')}</SectionTitle>
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
                on={preloadOnStart}
                onChange={(next) => void commitPreloadOnStart(next)}
                disabled={loadingConfig || !config || savingPreload}
              />
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
          </>
        )}

        {active === 'storage' && (
          <>
            <SectionTitle>{t('settings.storage')}</SectionTitle>
            <div style={stS.infoBox}>
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
          </>
        )}

        {active === 'general' && (
          <>
            <SectionTitle>{t('settings.general')}</SectionTitle>
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
  progressTrack: {
    height: 4,
    borderRadius: 2,
    background: 'rgba(38,37,30,0.08)',
    marginBottom: 8,
    overflow: 'hidden',
  },
  progressFill: {
    height: '100%',
    background: 'var(--amber)',
    transition: 'width 0.3s ease-out',
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
