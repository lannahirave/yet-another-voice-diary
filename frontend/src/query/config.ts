import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
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
import { loadModel, unloadModel } from '../api/models'
import type { ApiConfig } from '../types/api'
import { queryKeys } from './keys'

export function useConfigQuery() {
  return useQuery({
    queryKey: queryKeys.config.current(),
    queryFn: getConfig,
  })
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
