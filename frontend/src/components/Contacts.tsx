import { useEffect, useState } from 'react'
import type { CSSProperties } from 'react'
import { useTranslation } from 'react-i18next'
import {
  useContactUtterancesQuery,
  useContactsData,
  useCreateContactMutation,
  useDeleteContactMutation,
} from '../query/contacts'
import { fmtTime } from '../utils/format'
import type { Contact } from '../types/domain'

const confidenceColor = (v: number): string =>
  v >= 0.8 ? 'var(--green)' : v >= 0.65 ? 'var(--amber)' : 'var(--text-dim)'

type TabId = 'voiceprint' | 'utterances' | 'notes'

const fmtMs = (ms: number): string => {
  const s = Math.max(0, Math.floor(ms / 1000))
  const m = Math.floor(s / 60)
  return `${m}:${String(s % 60).padStart(2, '0')}`
}

export function Contacts() {
  const { t } = useTranslation()
  const { contacts } = useContactsData()
  const createContactMutation = useCreateContactMutation()
  const deleteContactMutation = useDeleteContactMutation()

  const [selected, setSelected] = useState<string | null>(null)
  const [tab, setTab] = useState<TabId>('voiceprint')
  const [search, setSearch] = useState('')
  const [notes, setNotes] = useState<Record<string, string>>({})
  const [newName, setNewName] = useState('')
  const [creating, setCreating] = useState(false)

  useEffect(() => {
    if (contacts.length === 0) {
      setSelected(null)
      return
    }
    if (!selected || !contacts.some((contact) => contact.id === selected)) {
      setSelected(contacts[0].id)
    }
  }, [contacts, selected])

  const utterancesQuery = useContactUtterancesQuery(selected, tab === 'utterances')

  const contact: Contact | null = contacts.find((item) => item.id === selected) ?? null
  const filtered = contacts.filter((item) =>
    item.name.toLowerCase().includes(search.toLowerCase()),
  )

  const handleDelete = async (id: string) => {
    await deleteContactMutation.mutateAsync(id).catch(() => undefined)
    setSelected(null)
  }

  const handleCreate = async () => {
    if (!newName.trim()) return
    const created = await createContactMutation
      .mutateAsync({ name: newName.trim() })
      .catch(() => null)
    if (!created) return
    setNewName('')
    setCreating(false)
    setSelected(created.id)
  }

  return (
    <div style={ctS.root}>
      <div style={ctS.list}>
        <div style={ctS.listHeader}>
          <div style={ctS.searchBox}>
            <span style={{ color: 'var(--text-dim)', fontSize: 13 }}>⌕</span>
            <input
              placeholder={t('contacts.searchPlaceholder')}
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              style={ctS.searchInput}
            />
          </div>
        </div>
        <div style={{ flex: 1, overflowY: 'auto' }}>
          {filtered.map((item) => (
            <div
              key={item.id}
              onClick={() => setSelected(item.id)}
              style={{
                ...ctS.contactRow,
                ...(selected === item.id ? ctS.contactRowActive : {}),
              }}
            >
              {selected === item.id && <div style={ctS.activeLine} />}
              <div
                style={{
                  width: 34,
                  height: 34,
                  borderRadius: '50%',
                  flexShrink: 0,
                  background: `${item.color}18`,
                  border: `1.5px solid ${item.color}55`,
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  fontSize: 12,
                  fontWeight: 700,
                  color: item.color,
                  fontFamily: 'var(--mono)',
                }}
              >
                {item.initials}
              </div>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 13, fontWeight: 500, color: 'var(--text)' }}>
                  {item.name}
                </div>
                <div style={{ fontSize: 11, color: 'var(--text-dim)', fontFamily: 'var(--mono)' }}>
                  {t('contacts.sessionsCount', { count: item.sessions })}
                </div>
              </div>
              {item.totalTime > 0 && (
                <div style={{ fontSize: 10, color: 'var(--text-dim)', fontFamily: 'var(--mono)' }}>
                  {fmtTime(item.totalTime)}
                </div>
              )}
            </div>
          ))}
          {filtered.length === 0 && (
            <div style={{ padding: '20px 14px', color: 'var(--text-dim)', fontSize: 13 }}>
              {t('contacts.empty')}
            </div>
          )}
        </div>
        <div style={ctS.listFooter}>
          {creating ? (
            <div style={{ display: 'flex', gap: 6 }}>
              <input
                autoFocus
                placeholder={t('contacts.newContactPlaceholder')}
                value={newName}
                onChange={(e) => setNewName(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') void handleCreate()
                  if (e.key === 'Escape') setCreating(false)
                }}
                style={{ ...ctS.searchInput, flex: 1, border: '1px solid var(--accent)', borderRadius: 6, padding: '6px 8px' }}
              />
              <button onClick={() => void handleCreate()} style={ctS.newBtn}>✓</button>
            </div>
          ) : (
            <button onClick={() => setCreating(true)} style={ctS.newBtn}>
              {t('contacts.newContact')}
            </button>
          )}
        </div>
      </div>

      {contact && (
        <div style={ctS.profile}>
          <div style={ctS.hero}>
            <div
              style={{
                width: 52,
                height: 52,
                borderRadius: '50%',
                flexShrink: 0,
                background: `${contact.color}18`,
                border: `2px solid ${contact.color}55`,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                fontSize: 18,
                fontWeight: 700,
                color: contact.color,
                fontFamily: 'var(--mono)',
              }}
            >
              {contact.initials}
            </div>
            <div style={{ flex: 1 }}>
              <div style={{ fontSize: 18, fontWeight: 600, color: 'var(--text)', letterSpacing: '-0.3px' }}>
                {contact.name}
              </div>
              <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 2, fontFamily: 'var(--serif)', fontStyle: 'italic' }}>
                {t('contacts.metFrom', { date: contact.firstMet })}
              </div>
              <div style={{ display: 'flex', gap: 20, marginTop: 12 }}>
                {(
                  [
                    [contact.sessions, t('contacts.sessionsLabel')],
                    [contact.profileCount, t('contacts.profilesLabel')],
                  ] as Array<[string | number, string]>
                ).map(([value, label]) => (
                  <div key={label}>
                    <div style={{ fontSize: 16, fontWeight: 700, color: 'var(--text)', fontFamily: 'var(--mono)' }}>
                      {value}
                    </div>
                    <div style={{ fontSize: 10, color: 'var(--text-dim)', fontFamily: 'var(--mono)' }}>
                      {label}
                    </div>
                  </div>
                ))}
              </div>
            </div>
            <button
              style={ctS.deleteBtn}
              title={t('contacts.deleteTitle')}
              onClick={() => void handleDelete(contact.id)}
            >
              ✕
            </button>
          </div>

          <div style={ctS.tabs}>
            {(
              [
                ['voiceprint', t('contacts.tabVoiceprint')],
                ['utterances', t('contacts.tabUtterances')],
                ['notes', t('contacts.tabNotes')],
              ] as const
            ).map(([tabId, label]) => (
              <button
                key={tabId}
                onClick={() => setTab(tabId as TabId)}
                style={{ ...ctS.tab, ...(tab === tabId ? ctS.tabActive : {}) }}
              >
                {label}
              </button>
            ))}
          </div>

          <div style={ctS.tabBody}>
            {tab === 'voiceprint' && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
                {contact.confidence > 0 ? (
                  <div style={ctS.vpCard}>
                    <div style={ctS.vpRow}>
                      <div style={ctS.vpLabel}>{t('contacts.confidenceLabel')}</div>
                      <div style={ctS.vpBarWrap}>
                        <div
                          style={{
                            ...ctS.vpBarFill,
                            width: `${contact.confidence * 100}%`,
                            background: `${confidenceColor(contact.confidence)}99`,
                          }}
                        />
                      </div>
                      <div style={{ ...ctS.vpVal, color: confidenceColor(contact.confidence) }}>
                        {contact.confidence.toFixed(2)}
                      </div>
                    </div>
                  </div>
                ) : (
                  <div style={{ color: 'var(--text-dim)', fontSize: 13 }}>
                    {t('contacts.voiceprintUnavailable')}
                  </div>
                )}
                <button
                  style={{ ...ctS.updateBtn, opacity: contact.profileCount >= 2 ? 1 : 0.4 }}
                  disabled={contact.profileCount < 2}
                >
                  {t('contacts.updateProfile')}
                </button>
              </div>
            )}

              {tab === 'utterances' && (
                <div style={ctS.utterancesList}>
                  {utterancesQuery.isLoading && (
                    <div style={ctS.utterancesEmpty}>
                      {t('contacts.utterancesLoading')}
                    </div>
                  )}
                  {!utterancesQuery.isLoading && (utterancesQuery.data?.length ?? 0) === 0 && (
                    <div style={ctS.utterancesEmpty}>
                      {t('contacts.utterancesEmpty')}
                    </div>
                  )}
                  {!utterancesQuery.isLoading &&
                    (() => {
                      const utterances = utterancesQuery.data ?? []
                      const grouped: { label: string; items: typeof utterances }[] = []
                      for (const u of utterances) {
                        const dateStr = u.session_started_at
                          ? new Date(u.session_started_at).toLocaleDateString('uk-UA', {
                              day: 'numeric',
                              month: 'long',
                              year: 'numeric',
                            })
                          : ''
                        const label = dateStr || '—'
                        const last = grouped[grouped.length - 1]
                        if (last && last.label === label) {
                          last.items.push(u)
                        } else {
                          grouped.push({ label, items: [u] })
                        }
                      }
                      return grouped.map((group) => (
                        <div key={group.label}>
                          <div style={ctS.utteranceDayHeader}>{group.label}</div>
                          {group.items.map((utterance) => (
                            <div key={utterance.id} style={ctS.utteranceRow}>
                              <div style={ctS.utteranceMeta}>{fmtMs(utterance.started_ms)}</div>
                              <div style={ctS.utteranceText}>{utterance.transcript}</div>
                            </div>
                          ))}
                        </div>
                      ))
                    })()}
                </div>
              )}

            {tab === 'notes' && (
              <textarea
                placeholder={t('contacts.notesPlaceholder')}
                value={notes[contact.id] ?? ''}
                onChange={(e) =>
                  setNotes((current) => ({ ...current, [contact.id]: e.target.value }))
                }
                style={ctS.notesArea}
              />
            )}
          </div>
        </div>
      )}
    </div>
  )
}

const ctS: Record<string, CSSProperties> = {
  root: { display: 'flex', height: '100vh', background: 'var(--bg)', fontFamily: 'var(--sans)' },
  list: {
    width: 252,
    borderRight: '1px solid var(--border)',
    display: 'flex',
    flexDirection: 'column',
    flexShrink: 0,
    background: 'var(--surface)',
  },
  listHeader: {
    padding: '12px 12px 10px',
    borderBottom: '1px solid var(--border)',
    flexShrink: 0,
    background: 'var(--surface)',
    position: 'relative',
    zIndex: 2,
  },
  searchBox: {
    display: 'flex',
    gap: 8,
    background: 'var(--bg)',
    border: '1px solid var(--border)',
    borderRadius: 7,
    padding: '7px 10px',
    alignItems: 'center',
  },
  searchInput: {
    background: 'none',
    border: 'none',
    outline: 'none',
    color: 'var(--text)',
    fontSize: 13,
    width: '100%',
  },
  contactRow: {
    display: 'flex',
    alignItems: 'center',
    gap: 10,
    padding: '11px 14px',
    cursor: 'pointer',
    position: 'relative',
    transition: 'background 0.1s',
  },
  contactRowActive: { background: 'rgba(38,37,30,0.04)' },
  activeLine: {
    position: 'absolute',
    left: 0,
    top: '20%',
    bottom: '20%',
    width: 2,
    background: 'var(--accent)',
    borderRadius: 1,
  },
  listFooter: {
    padding: '10px 14px',
    borderTop: '1px solid var(--border)',
    flexShrink: 0,
    background: 'var(--surface)',
    position: 'relative',
    zIndex: 2,
  },
  newBtn: {
    width: '100%',
    background: 'var(--surface2)',
    border: '1px solid var(--border)',
    color: 'var(--text-muted)',
    borderRadius: 7,
    padding: '8px',
    fontSize: 13,
    cursor: 'pointer',
  },
  profile: { flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' },
  hero: {
    display: 'flex',
    gap: 16,
    padding: '22px 26px',
    borderBottom: '1px solid var(--border)',
    alignItems: 'flex-start',
    background: 'var(--surface)',
  },
  deleteBtn: {
    background: 'none',
    border: 'none',
    color: 'var(--text-dim)',
    cursor: 'pointer',
    fontSize: 13,
    padding: 4,
  },
  tabs: {
    display: 'flex',
    borderBottom: '1px solid var(--border)',
    padding: '0 26px',
    background: 'var(--surface)',
  },
  tab: {
    background: 'none',
    border: 'none',
    borderBottom: '2px solid transparent',
    padding: '11px 14px',
    color: 'var(--text-muted)',
    fontSize: 13,
    fontWeight: 500,
    cursor: 'pointer',
    marginBottom: -1,
  },
  tabActive: { color: 'var(--text)', borderBottomColor: 'var(--accent)' },
  tabBody: { flex: 1, overflowY: 'auto', padding: '22px 26px' },
  vpCard: {
    background: 'var(--surface)',
    border: '1px solid var(--border)',
    borderRadius: 8,
    padding: '16px 18px',
    display: 'flex',
    flexDirection: 'column',
    gap: 14,
  },
  vpRow: { display: 'flex', alignItems: 'center', gap: 12 },
  vpLabel: { fontSize: 12, color: 'var(--text-muted)', width: 110, flexShrink: 0 },
  vpBarWrap: {
    flex: 1,
    height: 4,
    background: 'var(--surface3)',
    borderRadius: 2,
    overflow: 'hidden',
  },
  vpBarFill: { height: '100%', borderRadius: 2, transition: 'width 0.6s' },
  vpVal: { fontSize: 12, fontFamily: 'var(--mono)', width: 72, textAlign: 'right', flexShrink: 0 },
  updateBtn: {
    background: 'var(--surface)',
    border: '1px solid var(--border)',
    color: 'var(--text)',
    borderRadius: 7,
    padding: '9px 16px',
    fontSize: 13,
    cursor: 'pointer',
  },
  notesArea: {
    width: '100%',
    minHeight: 280,
    background: 'var(--surface)',
    border: '1px solid var(--border)',
    borderRadius: 8,
    color: 'var(--text)',
    fontSize: 13.5,
    fontFamily: 'var(--mono)',
    padding: '14px',
    outline: 'none',
    resize: 'none',
    lineHeight: 1.6,
    boxSizing: 'border-box',
  },
  utterancesList: { display: 'flex', flexDirection: 'column', gap: 8 },
  utteranceDayHeader: {
    fontSize: 11,
    fontWeight: 600,
    color: 'var(--text-muted)',
    fontFamily: 'var(--mono)',
    textTransform: 'uppercase',
    letterSpacing: '0.08em',
    padding: '10px 0 4px 0',
    borderBottom: '1px solid var(--border)',
    marginBottom: 4,
  },
  utteranceRow: {
    display: 'grid',
    gridTemplateColumns: '52px 1fr',
    gap: 12,
    alignItems: 'baseline',
    padding: '8px 10px',
    borderRadius: 6,
    background: 'var(--surface)',
    border: '1px solid var(--border)',
  },
  utteranceMeta: {
    fontFamily: 'var(--mono)',
    fontSize: 11,
    color: 'var(--text-dim)',
  },
  utteranceText: { fontSize: 13.5, color: 'var(--text)', lineHeight: 1.5 },
  utterancesEmpty: {
    fontSize: 13,
    color: 'var(--text-dim)',
    fontStyle: 'italic',
  },
}
