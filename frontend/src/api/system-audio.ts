/**
 * Whole-system audio loopback in Electron via `getDisplayMedia`.
 *
 * The main process grants a screen source plus `audio: 'loopback'` through
 * `session.setDisplayMediaRequestHandler(...)`. The renderer must request
 * both audio and video, even though the application only consumes the audio
 * track; the legacy audio-only desktop `getUserMedia` route crashes the
 * renderer in current Electron/Chromium on Windows.
 */

interface ElectronAPI {
  platform?: string
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
  return (
    typeof window !== 'undefined' &&
    window.electronAPI?.platform === 'win32' &&
    !!navigator.mediaDevices?.getDisplayMedia
  )
}

export async function getSystemAudioStream(): Promise<MediaStream> {
  if (!window.electronAPI) {
    throw new SystemAudioUnavailableError(
      'System-audio capture is only available in the Electron desktop app',
    )
  }

  if (window.electronAPI.platform !== 'win32') {
    throw new SystemAudioUnavailableError(
      'System-audio loopback is currently supported only on Windows',
    )
  }

  if (!navigator.mediaDevices?.getDisplayMedia) {
    throw new SystemAudioUnavailableError(
      'This runtime does not support desktop loopback capture',
    )
  }

  const stream = await navigator.mediaDevices.getDisplayMedia({
    audio: true,
    video: true,
  })

  if (stream.getAudioTracks().length === 0) {
    stream.getTracks().forEach((track) => track.stop())
    throw new SystemAudioUnavailableError(
      'Desktop capture started without an audio loopback track',
    )
  }

  return stream
}
