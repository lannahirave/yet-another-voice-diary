import { afterEach, describe, expect, it, vi } from 'vitest'
import { getSystemAudioStream, isSystemAudioSupported, SystemAudioUnavailableError } from './system-audio'

function installElectron(platform: string) {
  Object.defineProperty(window, 'electronAPI', { configurable: true, value: { platform } })
}

function installMediaDevices(getDisplayMedia?: typeof navigator.mediaDevices.getDisplayMedia) {
  Object.defineProperty(navigator, 'mediaDevices', {
    configurable: true,
    value: getDisplayMedia ? { getDisplayMedia } : undefined,
  })
}

describe('system audio lifecycle', () => {
  afterEach(() => {
    vi.restoreAllMocks()
    Object.defineProperty(window, 'electronAPI', { configurable: true, value: undefined })
    installMediaDevices()
  })

  it('reports support only for Windows Electron with display capture available', () => {
    installMediaDevices(vi.fn())

    installElectron('linux')
    expect(isSystemAudioSupported()).toBe(false)

    installElectron('win32')
    expect(isSystemAudioSupported()).toBe(true)

    installMediaDevices()
    expect(isSystemAudioSupported()).toBe(false)
  })

  it('rejects when Electron is unavailable or the platform is unsupported', async () => {
    installMediaDevices(vi.fn())
    await expect(getSystemAudioStream()).rejects.toThrow(
      'only available in the Electron desktop app',
    )

    installElectron('linux')
    await expect(getSystemAudioStream()).rejects.toThrow('currently supported only on Windows')
  })

  it('rejects when desktop capture is unavailable or rejects', async () => {
    installElectron('win32')
    installMediaDevices()
    await expect(getSystemAudioStream()).rejects.toBeInstanceOf(SystemAudioUnavailableError)

    const captureError = new Error('permission denied')
    const getDisplayMedia = vi.fn().mockRejectedValue(captureError)
    installMediaDevices(getDisplayMedia)

    await expect(getSystemAudioStream()).rejects.toBe(captureError)
    expect(getDisplayMedia).toHaveBeenCalledWith({ audio: true, video: true })
  })

  it('returns a valid stream without stopping any of its tracks', async () => {
    installElectron('win32')
    const audioStop = vi.fn()
    const videoStop = vi.fn()
    const getTracks = vi.fn(() => [{ stop: audioStop }, { stop: videoStop }])
    const stream = { getAudioTracks: () => [{ stop: audioStop }], getTracks } as unknown as MediaStream
    const getDisplayMedia = vi.fn().mockResolvedValue(stream)
    installMediaDevices(getDisplayMedia)

    await expect(getSystemAudioStream()).resolves.toBe(stream)
    expect(getDisplayMedia).toHaveBeenCalledWith({ audio: true, video: true })
    expect(getTracks).not.toHaveBeenCalled()
    expect(audioStop).not.toHaveBeenCalled()
    expect(videoStop).not.toHaveBeenCalled()
  })

  it('stops every captured track exactly once when audio is absent', async () => {
    installElectron('win32')
    const stops = [vi.fn(), vi.fn(), vi.fn()]
    const tracks = stops.map((stop) => ({ stop }))
    const getTracks = vi.fn(() => tracks)
    const stream = {
      getAudioTracks: () => [],
      getTracks,
    } as unknown as MediaStream
    installMediaDevices(vi.fn().mockResolvedValue(stream))

    await expect(getSystemAudioStream()).rejects.toThrow('without an audio loopback track')
    expect(getTracks).toHaveBeenCalledOnce()
    stops.forEach((stop) => expect(stop).toHaveBeenCalledOnce())
  })
})
