interface ToggleProps {
  on: boolean
  onChange: (next: boolean) => void
  disabled?: boolean
}

export function Toggle({ on, onChange, disabled }: ToggleProps) {
  return (
    <div
      onClick={() => {
        if (disabled) return
        onChange(!on)
      }}
      style={{
        width: 36,
        height: 20,
        borderRadius: 9999,
        flexShrink: 0,
        cursor: disabled ? 'default' : 'pointer',
        opacity: disabled ? 0.55 : 1,
        background: on ? 'var(--accent)' : 'var(--surface3)',
        border: '1px solid var(--border)',
        position: 'relative',
        transition: 'background 0.18s',
      }}
    >
      <div
        style={{
          position: 'absolute',
          top: 2,
          left: on ? 18 : 2,
          width: 14,
          height: 14,
          borderRadius: '50%',
          background: '#fff',
          transition: 'left 0.18s',
          boxShadow: 'rgba(0,0,0,0.12) 0 1px 3px',
        }}
      />
    </div>
  )
}
