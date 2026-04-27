export function fmt(secs: number): string {
  const m = Math.floor(secs / 60).toString().padStart(2, '0')
  const s = (secs % 60).toString().padStart(2, '0')
  return `${m}:${s}`
}

export function fmtTime(secs: number): string {
  if (secs < 3600) return `${Math.floor(secs / 60)}хв`
  return `${Math.floor(secs / 3600)}г ${Math.floor((secs % 3600) / 60)}хв`
}
