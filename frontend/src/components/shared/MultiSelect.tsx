import { useCallback, useEffect, useRef, useState } from 'react'
import type { CSSProperties } from 'react'

export interface MultiSelectOption {
  value: string
  label: string
}

interface MultiSelectProps {
  options: MultiSelectOption[]
  selected: string[]
  onChange: (selected: string[]) => void
  placeholder?: string
  disabled?: boolean
  dataTestId?: string
}

const stS: Record<string, CSSProperties> = {
  outer: {
    position: 'relative',
    userSelect: 'none',
  },
  trigger: {
    display: 'flex',
    flexWrap: 'wrap',
    gap: 4,
    alignItems: 'center',
    minHeight: 32,
    padding: '3px 6px',
    border: '1px solid var(--border)',
    borderRadius: 6,
    background: 'var(--surface2)',
    cursor: 'pointer',
    fontSize: 12,
    fontFamily: 'var(--mono)',
  },
  triggerDisabled: {
    cursor: 'default',
    opacity: 0.55,
  },
  placeholder: {
    color: 'var(--text-muted)',
    padding: '2px 4px',
  },
  badge: {
    display: 'inline-flex',
    alignItems: 'center',
    gap: 3,
    background: 'rgba(245,78,0,0.1)',
    border: '1px solid rgba(245,78,0,0.35)',
    color: 'var(--accent)',
    borderRadius: 4,
    padding: '1px 4px 1px 6px',
    fontSize: 11.5,
    fontFamily: 'var(--mono)',
    lineHeight: '18px',
  },
  badgeRemove: {
    display: 'inline-flex',
    alignItems: 'center',
    justifyContent: 'center',
    width: 14,
    height: 14,
    borderRadius: 3,
    border: 'none',
    background: 'transparent',
    color: 'var(--accent)',
    cursor: 'pointer',
    fontSize: 10,
    padding: 0,
    lineHeight: 1,
  },
  more: {
    color: 'var(--text-muted)',
    fontSize: 11,
    padding: '1px 4px',
  },
  chevron: {
    marginLeft: 'auto',
    color: 'var(--text-muted)',
    fontSize: 10,
    paddingRight: 2,
  },
  dropdown: {
    position: 'absolute',
    top: '100%',
    left: 0,
    right: 0,
    marginTop: 3,
    background: 'var(--surface)',
    border: '1px solid var(--border)',
    borderRadius: 6,
    boxShadow: '0 4px 16px rgba(0,0,0,0.12)',
    zIndex: 100,
    overflow: 'hidden',
  },
  search: {
    width: '100%',
    border: 'none',
    borderBottom: '1px solid var(--border)',
    padding: '6px 10px',
    fontSize: 12,
    fontFamily: 'var(--mono)',
    color: 'var(--text)',
    background: 'transparent',
    outline: 'none',
    boxSizing: 'border-box',
  },
  list: {
    maxHeight: 180,
    overflowY: 'auto',
    padding: '4px 0',
  },
  optionRow: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
    padding: '5px 10px',
    cursor: 'pointer',
    fontSize: 12,
    fontFamily: 'var(--mono)',
    color: 'var(--text)',
    transition: 'background 0.1s',
  },
  optionRowSelected: {
    background: 'rgba(245,78,0,0.06)',
  },
  checkbox: {
    width: 14,
    height: 14,
    borderRadius: 3,
    border: '1.5px solid var(--border)',
    flexShrink: 0,
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    fontSize: 10,
  },
  checkboxChecked: {
    background: 'var(--accent)',
    borderColor: 'var(--accent)',
    color: '#fff',
  },
  footer: {
    borderTop: '1px solid var(--border)',
    padding: 0,
  },
  clearBtn: {
    width: '100%',
    border: 'none',
    background: 'none',
    padding: '6px 10px',
    color: 'var(--text-muted)',
    fontSize: 11.5,
    fontFamily: 'var(--mono)',
    cursor: 'pointer',
    textAlign: 'left',
  },
  noMatch: {
    padding: '8px 10px',
    color: 'var(--text-muted)',
    fontSize: 11.5,
    fontFamily: 'var(--mono)',
    textAlign: 'center',
  },
}

const MAX_BADGES = 3

export function MultiSelect({
  options,
  selected,
  onChange,
  placeholder = 'Select...',
  disabled = false,
  dataTestId,
}: MultiSelectProps) {
  const [open, setOpen] = useState(false)
  const [search, setSearch] = useState('')
  const outerRef = useRef<HTMLDivElement>(null)
  const searchRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (!open) return
    const handler = (e: MouseEvent) => {
      if (outerRef.current && !outerRef.current.contains(e.target as Node)) {
        setOpen(false)
        setSearch('')
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [open])

  useEffect(() => {
    if (open) {
      searchRef.current?.focus()
    }
  }, [open])

  const toggleOption = useCallback(
    (value: string) => {
      const next = selected.includes(value)
        ? selected.filter((v) => v !== value)
        : [...selected, value]
      onChange(next)
    },
    [selected, onChange],
  )

  const clearAll = useCallback(() => {
    onChange([])
  }, [onChange])

  const selectedSet = new Set(selected)
  const selectedOptions = options.filter((o) => selectedSet.has(o.value))
  const visibleBadges = selectedOptions.slice(0, MAX_BADGES)
  const extraCount = selectedOptions.length - MAX_BADGES
  const filtered = options.filter((o) =>
    o.label.toLowerCase().includes(search.toLowerCase()),
  )

  const toggle = () => {
    if (disabled) return
    setOpen((prev) => {
      if (prev) setSearch('')
      return !prev
    })
  }

  return (
    <div ref={outerRef} style={stS.outer} data-testid={dataTestId}>
      <div
        onClick={toggle}
        style={{
          ...stS.trigger,
          ...(disabled ? stS.triggerDisabled : {}),
        }}
        role="combobox"
        aria-expanded={open}
      >
        {selectedOptions.length === 0 && (
          <span style={stS.placeholder}>{placeholder}</span>
        )}
        {visibleBadges.map((o) => (
          <span
            key={o.value}
            style={stS.badge}
            data-testid={`ms-badge-${o.value}`}
          >
            {o.label}
            <button
              style={stS.badgeRemove}
              data-testid={`ms-remove-${o.value}`}
              onClick={(e) => {
                e.stopPropagation()
                onChange(selected.filter((v) => v !== o.value))
              }}
            >
              ×
            </button>
          </span>
        ))}
        {extraCount > 0 && (
          <span style={stS.more}>+{extraCount} more</span>
        )}
        <span style={stS.chevron}>{open ? '▲' : '▼'}</span>
      </div>
      {open && (
        <div style={stS.dropdown}>
          <input
            ref={searchRef}
            style={stS.search}
            placeholder="Search..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            data-testid="ms-search"
          />
          <div style={stS.list}>
            {filtered.length === 0 && (
              <div style={stS.noMatch}>No matches</div>
            )}
            {filtered.map((o) => {
              const isChecked = selectedSet.has(o.value)
              return (
                <div
                  key={o.value}
                  style={{
                    ...stS.optionRow,
                    ...(isChecked ? stS.optionRowSelected : {}),
                  }}
                  data-testid={`ms-option-${o.value}`}
                  onClick={() => toggleOption(o.value)}
                >
                  <span
                    style={{
                      ...stS.checkbox,
                      ...(isChecked ? stS.checkboxChecked : {}),
                    }}
                  >
                    {isChecked ? '✓' : ''}
                  </span>
                  <span>{o.label}</span>
                </div>
              )
            })}
          </div>
          {selectedOptions.length > 0 && (
            <div style={stS.footer}>
              <button
                style={stS.clearBtn}
                data-testid="ms-clear"
                onClick={clearAll}
              >
                Clear all
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
