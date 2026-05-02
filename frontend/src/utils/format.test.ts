import { describe, expect, it } from 'vitest'
import { fmt, fmtTime } from './format'

describe('fmt', () => {
  it('formats zero seconds', () => {
    expect(fmt(0)).toBe('00:00')
  })

  it('formats seconds under a minute', () => {
    expect(fmt(7)).toBe('00:07')
    expect(fmt(45)).toBe('00:45')
    expect(fmt(59)).toBe('00:59')
  })

  it('formats exactly one minute', () => {
    expect(fmt(60)).toBe('01:00')
  })

  it('formats minutes and seconds', () => {
    expect(fmt(75)).toBe('01:15')
    expect(fmt(130)).toBe('02:10')
    expect(fmt(599)).toBe('09:59')
  })

  it('formats values exceeding one hour', () => {
    expect(fmt(3661)).toBe('61:01')
    expect(fmt(7200)).toBe('120:00')
  })
})

describe('fmtTime', () => {
  it('formats under one hour with minutes only', () => {
    expect(fmtTime(0)).toBe('0хв')
    expect(fmtTime(60)).toBe('1хв')
    expect(fmtTime(120)).toBe('2хв')
    expect(fmtTime(3599)).toBe('59хв')
  })

  it('formats one hour or more with hours and minutes', () => {
    expect(fmtTime(3600)).toBe('1г 0хв')
    expect(fmtTime(3660)).toBe('1г 1хв')
    expect(fmtTime(5400)).toBe('1г 30хв')
    expect(fmtTime(7200)).toBe('2г 0хв')
    expect(fmtTime(9000)).toBe('2г 30хв')
  })
})
