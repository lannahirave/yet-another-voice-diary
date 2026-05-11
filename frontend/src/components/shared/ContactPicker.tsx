import { useCallback, useEffect, useRef, useState } from 'react'
import type { CSSProperties } from 'react'
import { useTranslation } from 'react-i18next'
import { useContactsData, useCreateContactMutation } from '../../query/contacts'
import type { Contact } from '../../types/domain'

interface ContactPickerProps {
  selectedId: string | null
  onChange: (contactId: string | null) => void
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
    alignItems: 'center',
    gap: 8,
    minHeight: 32,
    padding: '3px 8px',
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
    padding: '2px 0',
  },
  avatarSmall: {
    width: 20,
    height: 20,
    borderRadius: '50%',
    flexShrink: 0,
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    fontSize: 9,
    fontWeight: 700,
    fontFamily: 'var(--mono)',
  },
  selectedName: {
    color: 'var(--text)',
    flex: 1,
  },
  clearBtn: {
    display: 'inline-flex',
    alignItems: 'center',
    justifyContent: 'center',
    width: 16,
    height: 16,
    borderRadius: 3,
    border: 'none',
    background: 'transparent',
    color: 'var(--text-muted)',
    cursor: 'pointer',
    fontSize: 10,
    padding: 0,
    lineHeight: 1,
    flexShrink: 0,
  },
  chevron: {
    color: 'var(--text-muted)',
    fontSize: 10,
    flexShrink: 0,
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
    maxHeight: 168,
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
    border: 'none',
    background: 'none',
    width: '100%',
    textAlign: 'left',
  },
  optionName: {
    flex: 1,
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap',
  },
  footer: {
    borderTop: '1px solid var(--border)',
    padding: 0,
  },
  createBtn: {
    width: '100%',
    border: 'none',
    background: 'none',
    padding: '6px 10px',
    color: 'var(--accent)',
    fontSize: 11.5,
    fontFamily: 'var(--mono)',
    cursor: 'pointer',
    textAlign: 'left',
  },
  createRow: {
    display: 'flex',
    gap: 6,
    padding: '4px 10px',
    alignItems: 'center',
  },
  createInput: {
    flex: 1,
    border: '1px solid var(--border)',
    borderRadius: 4,
    padding: '4px 8px',
    fontSize: 12,
    fontFamily: 'var(--mono)',
    color: 'var(--text)',
    background: 'var(--surface2)',
    outline: 'none',
  },
  noMatch: {
    padding: '8px 10px',
    color: 'var(--text-muted)',
    fontSize: 11.5,
    fontFamily: 'var(--mono)',
  },
}

export function ContactPicker({
  selectedId,
  onChange,
  placeholder = 'Select contact…',
  disabled = false,
  dataTestId,
}: ContactPickerProps) {
  const { t } = useTranslation()
  const { contacts, isLoading } = useContactsData()
  const createContactMutation = useCreateContactMutation()

  const [open, setOpen] = useState(false)
  const [search, setSearch] = useState('')
  const [creating, setCreating] = useState(false)
  const [newName, setNewName] = useState('')
  const outerRef = useRef<HTMLDivElement>(null)
  const searchRef = useRef<HTMLInputElement>(null)
  const createRef = useRef<HTMLInputElement>(null)

  const selectedContact = selectedId
    ? contacts.find((c) => c.id === selectedId) ?? null
    : null

  useEffect(() => {
    if (!open) return
    const handler = (e: MouseEvent) => {
      if (outerRef.current && !outerRef.current.contains(e.target as Node)) {
        setOpen(false)
        setSearch('')
        setCreating(false)
        setNewName('')
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [open])

  useEffect(() => {
    if (open && creating) {
      createRef.current?.focus()
    } else if (open) {
      searchRef.current?.focus()
    }
  }, [open, creating])

  const filtered = contacts.filter((c) =>
    c.name.toLowerCase().includes(search.toLowerCase()),
  )

  const handleSelect = useCallback(
    (contact: Contact) => {
      onChange(contact.id)
      setOpen(false)
      setSearch('')
    },
    [onChange],
  )

  const handleCreate = useCallback(async () => {
    const name = newName.trim()
    if (!name || createContactMutation.isPending) return
    try {
      const result = await createContactMutation.mutateAsync({ name })
      onChange(result.id)
      setOpen(false)
      setSearch('')
      setCreating(false)
      setNewName('')
    } catch {
      // mutation error handled by query layer
    }
  }, [newName, createContactMutation, onChange])

  const toggle = () => {
    if (disabled) return
    setOpen((prev) => {
      if (prev) {
        setSearch('')
        setCreating(false)
        setNewName('')
      }
      return !prev
    })
  }

  const avatarStyle = (contact: Contact): CSSProperties => ({
    ...stS.avatarSmall,
    background: `${contact.color}18`,
    color: contact.color,
    border: `1.5px solid ${contact.color}55`,
  })

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
        {selectedContact ? (
          <>
            <div style={avatarStyle(selectedContact)}>
              {selectedContact.initials}
            </div>
            <span style={stS.selectedName}>{selectedContact.name}</span>
            <button
              style={stS.clearBtn}
              data-testid={`cp-clear`}
              onClick={(e) => {
                e.stopPropagation()
                onChange(null)
              }}
            >
              ×
            </button>
          </>
        ) : (
          <span style={stS.placeholder}>{placeholder}</span>
        )}
        <span style={stS.chevron}>{open ? '▲' : '▼'}</span>
      </div>
      {open && (
        <div style={stS.dropdown}>
          {!creating && (
            <input
              ref={searchRef}
              style={stS.search}
              placeholder="Search contacts…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              data-testid="cp-search"
            />
          )}
          {creating ? (
            <div style={stS.createRow}>
              <input
                ref={createRef}
                style={stS.createInput}
                placeholder={t('contacts.newContactPlaceholder')}
                value={newName}
                onChange={(e) => setNewName(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') void handleCreate()
                  if (e.key === 'Escape') {
                    setCreating(false)
                    setNewName('')
                  }
                }}
                data-testid="cp-create-input"
              />
              <button
                onClick={() => void handleCreate()}
                disabled={!newName.trim() || createContactMutation.isPending}
                style={{
                  ...stS.createBtn,
                  width: 'auto',
                  padding: '4px 8px',
                  opacity: newName.trim() && !createContactMutation.isPending ? 1 : 0.4,
                }}
                data-testid="cp-create-confirm"
              >
                ✓
              </button>
            </div>
          ) : (
            <>
              <div style={stS.list}>
                {isLoading && (
                  <div style={stS.noMatch}>{t('common.loading')}</div>
                )}
                {!isLoading && filtered.length === 0 && (
                  <div style={stS.noMatch}>No contacts</div>
                )}
                {filtered.map((contact) => (
                  <button
                    key={contact.id}
                    style={{
                      ...stS.optionRow,
                      ...(contact.id === selectedId
                        ? { background: 'rgba(245,78,0,0.06)' }
                        : {}),
                    }}
                    data-testid={`cp-option-${contact.id}`}
                    onClick={() => handleSelect(contact)}
                  >
                    <div style={avatarStyle(contact)}>{contact.initials}</div>
                    <span style={stS.optionName}>{contact.name}</span>
                  </button>
                ))}
              </div>
              <div style={stS.footer}>
                <button
                  style={stS.createBtn}
                  data-testid="cp-create-btn"
                  onClick={() => {
                    setCreating(true)
                    setSearch('')
                  }}
                >
                  + {t('contacts.newContact')}
                </button>
              </div>
            </>
          )}
        </div>
      )}
    </div>
  )
}
