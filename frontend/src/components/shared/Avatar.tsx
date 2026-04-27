import type { CSSProperties } from 'react'
import type { Contact } from '../../types/domain'

interface AvatarProps {
  contact: Contact | null
  size?: number
}

export function Avatar({ contact, size = 32 }: AvatarProps) {
  const bg = contact ? `${contact.color}18` : 'transparent'
  const clr = contact ? contact.color : 'var(--text-dim)'
  const brd = contact
    ? `1.5px solid ${contact.color}55`
    : '1.5px dashed rgba(38,37,30,0.25)'

  const style: CSSProperties = {
    width: size,
    height: size,
    borderRadius: '50%',
    flexShrink: 0,
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    fontSize: size * 0.3,
    fontWeight: 700,
    fontFamily: 'var(--mono)',
    background: bg,
    color: clr,
    border: brd,
  }

  return <div style={style}>{contact ? contact.initials : '?'}</div>
}
