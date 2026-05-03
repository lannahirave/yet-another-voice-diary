import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  getSystemAudioStream,
  isSystemAudioSupported,
  SystemAudioUnavailableError,
} from './system-audio'

function setPlatform(platform: string | undefined) {
  Object.defineProperty(window, 'electronAPI', {
    configurable: true,
    value: platform
      ? {
          platform,
          enableLoopbackAudio: vi.fn(async () => undefined),
          disableLoopbackAudio: vi.fn(async () => undefined),
        }
      : undefined,
  })
}

function setGetDisplayMedia(
  fn: ((options?: DisplayMediaStreamOptions) => Promise<MediaStream>) | undefined,
) {
  Object.defineProperty(navigator, 'mediaDevices', {
    configurable: true,
    value: fn ? { getDisplayMedia: fn } : undefined,
  })
}

function makeTrack(kind: 'audio' | 'video', readyState: MediaStreamTrackState = 'live') {
  return {
    kind,
    readyState,
    stop: vi.fn(),
  } as unknown as MediaStreamTrack
}

function makeStream(tracks: MediaStreamTrack[]) {
  return {
    getTracks: () => tracks,
    getAudioTracks: () => tracks.filter((track) => track.kind === 'audio'),
    getVideoTracks: () => tracks.filter((track) => track.kind === 'video'),
    removeTrack: vi.fn(),
  } as unknown as MediaStream
}

beforeEach(() => {
  setPlatform(undefined)
  setGetDisplayMedia(undefined)
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe('isSystemAudioSupported', () => {
  it('supports Windows when getDisplayMedia is available', () => {
    setPlatform('win32')
    setGetDisplayMedia(vi.fn())

    expect(isSystemAudioSupported()).toBe(true)
  })

  it('supports macOS when getDisplayMedia is available', () => {
    setPlatform('darwin')
    setGetDisplayMedia(vi.fn())

    expect(isSystemAudioSupported()).toBe(true)
  })

  it('rejects unsupported platforms', () => {
    setPlatform('linux')
    setGetDisplayMedia(vi.fn())

    expect(isSystemAudioSupported()).toBe(false)
  })
})

describe('getSystemAudioStream', () => {
  it('requires Electron', async () => {
    setGetDisplayMedia(vi.fn())

    await expect(getSystemAudioStream()).rejects.toThrow(SystemAudioUnavailableError)
    await expect(getSystemAudioStream()).rejects.toThrow(
      'System-audio capture is only available in the Electron desktop app',
    )
  })

  it('rejects unsupported platforms', async () => {
    setPlatform('linux')
    setGetDisplayMedia(vi.fn())

    await expect(getSystemAudioStream()).rejects.toThrow(
      'System-audio capture is currently supported only on Windows and macOS',
    )
  })

  it('requires getDisplayMedia', async () => {
    setPlatform('darwin')

    await expect(getSystemAudioStream()).rejects.toThrow(
      'This runtime does not support desktop loopback capture',
    )
  })

  it('stops all tracks when desktop capture has no audio', async () => {
    setPlatform('win32')
    const video = makeTrack('video')
    const stream = makeStream([video])
    setGetDisplayMedia(vi.fn(async () => stream))

    await expect(getSystemAudioStream()).rejects.toThrow(
      'Desktop capture started without an audio loopback track',
    )
    expect(video.stop).toHaveBeenCalledOnce()
  })

  it('stops all tracks when macOS returns a dead audio track', async () => {
    setPlatform('darwin')
    const audio = makeTrack('audio', 'ended')
    const video = makeTrack('video')
    const stream = makeStream([audio, video])
    setGetDisplayMedia(vi.fn(async () => stream))

    await expect(getSystemAudioStream()).rejects.toThrow(
      'Desktop capture started without live system audio',
    )
    expect(audio.stop).toHaveBeenCalledOnce()
    expect(video.stop).toHaveBeenCalledOnce()
  })

  it('returns live audio and stops video tracks', async () => {
    setPlatform('darwin')
    const audio = makeTrack('audio')
    const video = makeTrack('video')
    const stream = makeStream([audio, video])
    const getDisplayMedia = vi.fn(async () => stream)
    setGetDisplayMedia(getDisplayMedia)

    await expect(getSystemAudioStream()).resolves.toBe(stream)
    expect(getDisplayMedia).toHaveBeenCalledWith({
      audio: {
        suppressLocalAudioPlayback: false,
      },
      video: true,
      monitorTypeSurfaces: 'include',
      systemAudio: 'include',
      surfaceSwitching: 'include',
      windowAudio: 'system',
    })
    expect(audio.stop).not.toHaveBeenCalled()
    expect(video.stop).toHaveBeenCalledOnce()
    expect(stream.removeTrack).toHaveBeenCalledWith(video)
  })
})
