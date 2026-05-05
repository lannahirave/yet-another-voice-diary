import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useMemo } from 'react'
import {
  getConfig,
  getStorageInfo,
  selectProvider,
  setBlocklistEnabled,
  setElevenLabsToken,
  setPipeline,
  setPreloadOnStart,
  setThreshold,
  setUnloadAfterStop,
} from '../api/config'
import { getModelStatus, loadModel, unloadModel } from '../api/models'
import type { ApiConfig } from '../types/api'
import { queryKeys } from './keys'

export function useConfigQuery() {
  return useQuery({
    queryKey: queryKeys.config.current(),
    queryFn: getConfig,
  })
}

/** Polls model status while any provider is loading — replaces SSE. */
export function useModelProgress(kind: string) {
  const statusQuery = useQuery({
    queryKey: ['models', 'status'],
    queryFn: getModelStatus,
    refetchInterval: (query) => {
      const status = query.state.data
      if (!status) return 1000
      const provider = status[kind]
      if (!provider || provider.state !== 'LOADING') return false
      return 1000
    },
  })
  const provider = statusQuery.data?.[kind]
  return useMemo(() => {
    if (!provider || provider.state !== 'LOADING') return null
    return { progress: _interpProgress(provider.state), state: provider.state, error: provider.error }
  }, [provider])
}

function _interpProgress(state: string): number {
  if (state === 'LOADED') return 1.0
  if (state === 'LOADING') return 0.05
  return 0.0
}

export function useSelectProviderMutation() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: ({ type, modelId }: { type: string; modelId: string }) =>
      selectProvider(type, modelId),
    onSuccess: async (config) => {
      queryClient.setQueryData<ApiConfig>(queryKeys.config.current(), config)
      await queryClient.invalidateQueries({ queryKey: queryKeys.config.current() })
    },
  })
}

export function useSetThresholdMutation() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (value: number) => setThreshold('speaker', value),
    onSuccess: async (config) => {
      queryClient.setQueryData<ApiConfig>(queryKeys.config.current(), config)
      await queryClient.invalidateQueries({ queryKey: queryKeys.config.current() })
    },
  })
}

export function useSetPipelineMutation() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (fields: Record<string, number>) => setPipeline(fields),
    onSuccess: async (config) => {
      queryClient.setQueryData<ApiConfig>(queryKeys.config.current(), config)
      await queryClient.invalidateQueries({ queryKey: queryKeys.config.current() })
    },
  })
}

export function useUnloadAfterStopMutation() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (value: boolean) => setUnloadAfterStop(value),
    onSuccess: async (config) => {
      queryClient.setQueryData<ApiConfig>(queryKeys.config.current(), config)
      await queryClient.invalidateQueries({ queryKey: queryKeys.config.current() })
    },
  })
}

export function usePreloadOnStartMutation() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (value: boolean) => setPreloadOnStart(value),
    onSuccess: async (config) => {
      queryClient.setQueryData<ApiConfig>(queryKeys.config.current(), config)
      await queryClient.invalidateQueries({ queryKey: queryKeys.config.current() })
    },
  })
}

export function useBlocklistEnabledMutation() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (value: boolean) => setBlocklistEnabled(value),
    onSuccess: async (config) => {
      queryClient.setQueryData<ApiConfig>(queryKeys.config.current(), config)
      await queryClient.invalidateQueries({ queryKey: queryKeys.config.current() })
    },
  })
}

export function useElevenLabsTokenMutation() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (token: string) => setElevenLabsToken(token),
    onSuccess: async (config) => {
      queryClient.setQueryData<ApiConfig>(queryKeys.config.current(), config)
      await queryClient.invalidateQueries({ queryKey: queryKeys.config.current() })
    },
  })
}

export function useStorageInfoQuery() {
  return useQuery({
    queryKey: queryKeys.config.storage(),
    queryFn: getStorageInfo,
  })
}

export function useModelLifecycleMutation() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async ({
      type,
      action,
    }: {
      type: string
      action: 'load' | 'unload'
    }) => {
      if (action === 'load') {
        await loadModel(type)
      } else {
        await unloadModel(type)
      }
      return getConfig()
    },
    onSuccess: async (config) => {
      queryClient.setQueryData<ApiConfig>(queryKeys.config.current(), config)
      await queryClient.invalidateQueries({ queryKey: queryKeys.config.current() })
    },
  })
}
