/**
 * Whole-system audio capture in Electron via `getDisplayMedia`.
 *
 * Windows uses Electron's `audio: 'loopback'` display-media grant. macOS uses
 * Chromium's desktop audio path, which still requires requesting video as part
 * of display capture; the application stops the video tracks immediately and
 * consumes only the audio track.
 */

interface ElectronAPI {
  platform?: string
  enableLoopbackAudio?: () => Promise<void>
  disableLoopbackAudio?: () => Promise<void>
}

type DisplayMediaOptionsWithAudioHints = DisplayMediaStreamOptions & {
  audio?: boolean | (MediaTrackConstraints & {
    suppressLocalAudioPlayback?: boolean
  })
  monitorTypeSurfaces?: 'include' | 'exclude'
  systemAudio?: 'include' | 'exclude'
  surfaceSwitching?: 'include' | 'exclude'
  windowAudio?: 'exclude' | 'window' | 'system'
}

declare global {
  interface Window {
    electronAPI?: ElectronAPI
  }
}

export class SystemAudioUnavailableError extends Error {
  constructor(message: string) {
    super(message)
    this.name = 'SystemAudioUnavailableError'
  }
}

export function isSystemAudioSupported(): boolean {
  if (typeof window === 'undefined') return false
  const platform = window.electronAPI?.platform
  return (
    (platform === 'win32' || platform === 'darwin') &&
    !!navigator.mediaDevices?.getDisplayMedia
  )
}

export async function getSystemAudioStream(): Promise<MediaStream> {
  if (!window.electronAPI) {
    throw new SystemAudioUnavailableError(
      'System-audio capture is only available in the Electron desktop app',
    )
  }

  if (
    window.electronAPI.platform !== 'win32' &&
    window.electronAPI.platform !== 'darwin'
  ) {
    throw new SystemAudioUnavailableError(
      'System-audio capture is currently supported only on Windows and macOS',
    )
  }

  if (!navigator.mediaDevices?.getDisplayMedia) {
    throw new SystemAudioUnavailableError(
      'This runtime does not support desktop loopback capture',
    )
  }

  await window.electronAPI.enableLoopbackAudio?.()

  let stream: MediaStream
  try {
    const displayMediaOptions: DisplayMediaOptionsWithAudioHints = {
      audio: {
        suppressLocalAudioPlayback: false,
      },
      video: true,
      monitorTypeSurfaces: 'include',
      systemAudio: 'include',
      surfaceSwitching: 'include',
      windowAudio: 'system',
    }

    stream = await navigator.mediaDevices.getDisplayMedia(displayMediaOptions)
  } finally {
    await window.electronAPI.disableLoopbackAudio?.()
  }

  const audioTracks = stream.getAudioTracks()
  const liveAudioTracks = audioTracks.filter((track) => track.readyState === 'live')

  if (liveAudioTracks.length === 0) {
    console.warn('[system-audio] no live audio tracks', {
      platform: window.electronAPI.platform,
      audioTracks: audioTracks.map((track) => ({
        id: track.id,
        label: track.label,
        enabled: track.enabled,
        muted: track.muted,
        readyState: track.readyState,
        settings: track.getSettings?.(),
      })),
      tracks: stream.getTracks().map((track) => ({
        kind: track.kind,
        id: track.id,
        label: track.label,
        enabled: track.enabled,
        muted: track.muted,
        readyState: track.readyState,
        settings: track.getSettings?.(),
      })),
    })
    stream.getTracks().forEach((track) => track.stop())
    throw new SystemAudioUnavailableError(
      window.electronAPI.platform === 'darwin'
        ? 'Desktop capture started without live system audio. Grant Screen & System Audio Recording permission, then restart the app.'
        : 'Desktop capture started without an audio loopback track',
    )
  }

  stream.getVideoTracks().forEach((track) => {
    track.stop()
    stream.removeTrack(track)
  })
  return stream
}
