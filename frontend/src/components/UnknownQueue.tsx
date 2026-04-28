import { useEffect, useState } from 'react'
import type { CSSProperties } from 'react'
import { useTranslation } from 'react-i18next'
import { useContactsData, useCreateContactMutation } from '../query/contacts'
import {
  useQueueListQuery,
  useQueueCountQuery,
  useResolveQueueClusterMutation,
  useSkipQueueClusterMutation,
} from '../query/queue'
import type { UnknownQueueItem } from '../types/domain'
import {
  deriveQueueSessionOptions,
  filterUnknownQueueItems,
  normalizeQueueSessionFilter,
} from '../utils/unknownQueueFilters'

interface UnknownQueueProps {
  onApplyLiveResolution?: (segmentIds: string[], contactId: string) => (() => void) | void
  currentSessionId?: string | null
}

export function UnknownQueue({ onApplyLiveResolution, currentSessionId = null }: UnknownQueueProps) {
  const { t } = useTranslation()
  const { contacts, contactById } = useContactsData()
  const PAGE_SIZE = 20
  const [offset, setOffset] = useState(0)
  const queueQuery = useQueueListQuery(PAGE_SIZE, offset)
  const countQuery = useQueueCountQuery()
  const createContactMutation = useCreateContactMutation()
  const resolveMutation = useResolveQueueClusterMutation({
    onApplyLiveResolution,
  })
  const skipMutation = useSkipQueueClusterMutation()

  const [newContactId, setNewContactId] = useState<string | null>(null)
  const [newContactName, setNewContactName] = useState('')
  const [pickExistingId, setPickExistingId] = useState<string | null>(null)
  const [pickExistingQuery, setPickExistingQuery] = useState('')
  const [searchQuery, setSearchQuery] = useState('')
  const [sessionFilter, setSessionFilter] = useState<string>('all')

  const items = queueQuery.data ?? []
  const totalCount = countQuery.data ?? 0
  const hasMore = offset + PAGE_SIZE < totalCount && items.length === PAGE_SIZE
  const error = queueQuery.error ? t('queue.backendUnavailable') : null
  const sessionOptions = deriveQueueSessionOptions(items)

  useEffect(() => {
    const normalizedFilter = normalizeQueueSessionFilter(
      sessionFilter,
      currentSessionId,
      sessionOptions,
    )
    if (normalizedFilter !== sessionFilter) {
      setSessionFilter(normalizedFilter)
    }
    setOffset(0)
  }, [currentSessionId, sessionFilter, sessionOptions])

  const filteredItems = filterUnknownQueueItems({
    items,
    searchQuery,
    sessionFilter,
    currentSessionId,
    lookupContactName: (contactId) => contactById(contactId)?.name ?? null,
  })

  const resolve = async (cluster: UnknownQueueItem, contactId: string) => {
    await resolveMutation.mutateAsync({ cluster, contactId }).catch(() => undefined)
  }

  const skip = async (cluster: UnknownQueueItem) => {
    await skipMutation.mutateAsync({ cluster }).catch(() => undefined)
  }

  const handleNewContact = async (cluster: UnknownQueueItem, name: string) => {
    const contact = await createContactMutation
      .mutateAsync({ name })
      .catch(() => null)
    if (!contact) return

    await resolve(cluster, contact.id)
    setNewContactId(null)
    setNewContactName('')
  }

  return (
    <div style={uqS.root}>
      <div style={uqS.topbar}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <span style={uqS.title}>{t('queue.title')}</span>
          <span style={uqS.badge}>{items.length}</span>
        </div>
        <div style={uqS.searchWrap}>
          <span style={{ color: 'var(--text-dim)', fontSize: 13 }}>⌕</span>
          <input
            placeholder={t('queue.searchPlaceholder')}
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            style={uqS.searchInput}
          />
          {searchQuery && (
            <button onClick={() => setSearchQuery('')} style={uqS.clearBtn}>
              ✕
            </button>
          )}
        </div>
      </div>
      <div style={uqS.filtersBar}>
        <span style={uqS.filterLabel}>{t('queue.sessionFilterLabel')}</span>
        <select
          value={sessionFilter}
          onChange={(e) => setSessionFilter(e.target.value)}
          style={uqS.filterSelect}
        >
          <option value="all">{t('queue.sessionFilterAll')}</option>
          {currentSessionId && (
            <option value="current">{t('queue.sessionFilterCurrent')}</option>
          )}
          {sessionOptions.map(({ sessionId, sessionTitle }) => (
            <option key={sessionId} value={sessionId}>
              {sessionTitle || sessionId}
            </option>
          ))}
        </select>
      </div>

      <div style={uqS.list}>
        {error && <div style={uqS.empty}><div style={{ fontSize: 14, color: 'var(--text-dim)' }}>{error}</div></div>}

        {!error && items.length === 0 && (
          <div style={uqS.empty}>
            <div style={{ fontSize: 28, color: 'var(--green)', marginBottom: 8 }}>✓</div>
            <div style={{ fontSize: 15, fontWeight: 600, color: 'var(--green)' }}>{t('queue.empty')}</div>
            <div style={{ fontSize: 13, color: 'var(--text-muted)', marginTop: 4 }}>{t('queue.emptySub')}</div>
          </div>
        )}

        {!error && items.length > 0 && filteredItems.length === 0 && (
          <div style={uqS.empty}>
            <div style={{ fontSize: 15, fontWeight: 600, color: 'var(--text)' }}>{t('queue.noMatches')}</div>
            <div style={{ fontSize: 13, color: 'var(--text-muted)', marginTop: 4 }}>{t('queue.searchPlaceholder')}</div>
          </div>
        )}

        {filteredItems.map((item, idx) => {
          const candidates = item.candidates.map((candidate) => ({
            ...candidate,
            contact: contactById(candidate.contactId),
          }))
          const queueBusy =
            resolveMutation.isPending && resolveMutation.variables?.cluster.id === item.id
          const skipBusy =
            skipMutation.isPending && skipMutation.variables?.cluster.id === item.id

          return (
            <div
              key={item.id}
              style={{
                ...uqS.card,
                ...(idx === 0 ? uqS.cardLead : null),
                position: 'relative',
                zIndex: pickExistingId === item.id ? 30 : 1,
              }}
            >
              <div style={uqS.cardHeader}>
                <div style={uqS.unkAvatar}>?</div>
                <div style={{ flex: 1 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                    <span style={uqS.cardLabel}>{t('queue.unknownSpeaker', { label: item.label })}</span>
                    {item.sessionTitle && (
                      <span style={uqS.cardSession}>{item.sessionTitle}</span>
                    )}
                  </div>
                  <div style={uqS.cardMeta}>{item.sessionDate}</div>
                </div>
                {item.totalDuration && (
                  <div style={{ textAlign: 'right', flexShrink: 0 }}>
                    <div style={uqS.cardDur}>{item.totalDuration}</div>
                    <div style={uqS.cardFrags}>
                      {t('queue.fragments', { count: item.fragmentCount })}
                    </div>
                  </div>
                )}
              </div>

              {item.quote && (
                <div style={uqS.quote}>
                  <div style={uqS.quoteBar} />
                  <div style={uqS.quoteText}>{item.quote}</div>
                </div>
              )}

              <div style={uqS.actions}>
                <span style={uqS.whoLabel}>{t('queue.whoIsThis')}</span>

                {candidates.map(({ contactId, score, contact }) => {
                  const name = contact?.name ?? contactId
                  const color = contact?.color ?? 'var(--text-dim)'
                  const initials = contact?.initials ?? contactId.slice(0, 2).toUpperCase()
                  return (
                    <button
                      key={contactId}
                      onClick={() => void resolve(item, contactId)}
                      disabled={queueBusy || skipBusy}
                      title={t('queue.similarityTitle', { percent: Math.round(score * 100) })}
                      style={uqS.candidatePill}
                      onMouseEnter={(e) => { e.currentTarget.style.background = 'var(--surface3)' }}
                      onMouseLeave={(e) => { e.currentTarget.style.background = 'var(--surface2)' }}
                    >
                      <div style={{
                        width: 18, height: 18, borderRadius: '50%', flexShrink: 0,
                        background: `${color}18`, border: `1.5px solid ${color}55`,
                        display: 'flex', alignItems: 'center', justifyContent: 'center',
                        fontSize: 7.5, fontWeight: 700, color, fontFamily: 'var(--mono)',
                      }}>
                        {initials}
                      </div>
                      <span>{name.split(' ')[0]}</span>
                      <span style={{ fontSize: 10, color: 'var(--text-dim)', fontFamily: 'var(--mono)' }}>
                        {Math.round(score * 100)}%
                      </span>
                    </button>
                  )
                })}

                {pickExistingId === item.id ? (
                  (() => {
                    const candidateIds = new Set(item.candidates.map((candidate) => candidate.contactId))
                    const query = pickExistingQuery.trim().toLowerCase()
                    const pool = contacts.filter((contact) => !candidateIds.has(contact.id))
                    const filtered = query
                      ? pool.filter((contact) => contact.name.toLowerCase().includes(query))
                      : pool

                    return (
                      <div style={uqS.pickerWrap}>
                        <input
                          autoFocus
                          placeholder={t('queue.pickExistingPlaceholder')}
                          value={pickExistingQuery}
                          onChange={(e) => setPickExistingQuery(e.target.value)}
                          onKeyDown={(e) => {
                            if (e.key === 'Escape') {
                              setPickExistingId(null)
                              setPickExistingQuery('')
                            }
                          }}
                          style={uqS.newContactInput}
                        />
                        <div style={uqS.pickerList}>
                          {filtered.length === 0 ? (
                            <div style={uqS.pickerEmpty}>{t('queue.noContacts')}</div>
                          ) : (
                            filtered.map((contact) => (
                              <button
                                key={contact.id}
                                onClick={() => {
                                  void resolve(item, contact.id)
                                  setPickExistingId(null)
                                  setPickExistingQuery('')
                                }}
                                style={uqS.pickerItem}
                                onMouseEnter={(e) => { e.currentTarget.style.background = 'var(--surface3)' }}
                                onMouseLeave={(e) => { e.currentTarget.style.background = 'transparent' }}
                              >
                                <div style={{
                                  width: 18, height: 18, borderRadius: '50%', flexShrink: 0,
                                  background: `${contact.color}18`, border: `1.5px solid ${contact.color}55`,
                                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                                  fontSize: 7.5, fontWeight: 700, color: contact.color, fontFamily: 'var(--mono)',
                                }}>
                                  {contact.initials}
                                </div>
                                <span>{contact.name}</span>
                              </button>
                            ))
                          )}
                        </div>
                      </div>
                    )
                  })()
                ) : (
                  <button
                    onClick={() => {
                      setPickExistingId(item.id)
                      setPickExistingQuery('')
                      setNewContactId(null)
                    }}
                    style={uqS.newBtn}
                  >
                    {t('queue.pickExisting')}
                  </button>
                )}

                {newContactId === item.id ? (
                  <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                    <input
                      autoFocus
                      placeholder={t('queue.namePlaceholder')}
                      value={newContactName}
                      onChange={(e) => setNewContactName(e.target.value)}
                      style={uqS.newContactInput}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter' && newContactName.trim()) {
                          void handleNewContact(item, newContactName.trim())
                        }
                      }}
                    />
                    <button
                      onClick={() => void handleNewContact(item, newContactName.trim())}
                      disabled={!newContactName.trim() || createContactMutation.isPending || queueBusy}
                      style={{ ...uqS.saveBtn, opacity: newContactName.trim() ? 1 : 0.4 }}
                    >
                      {t('queue.save')}
                    </button>
                  </div>
                ) : (
                  <button onClick={() => setNewContactId(item.id)} style={uqS.newBtn}>
                    {t('queue.newContact')}
                  </button>
                )}

                <button onClick={() => void skip(item)} style={uqS.skipBtn} disabled={queueBusy || skipBusy}>
                  {t('queue.skip')}
                </button>
              </div>
            </div>
          )
        })}
        {hasMore && !queueQuery.isFetching && (
          <div style={{ display: 'flex', justifyContent: 'center', padding: '12px 0' }}>
            <button
              onClick={() => setOffset((prev) => prev + PAGE_SIZE)}
              style={uqS.loadMoreBtn}
            >
              Load more ({totalCount - (offset + PAGE_SIZE)} remaining)
            </button>
          </div>
        )}
        {queueQuery.isFetching && offset > 0 && (
          <div style={{ textAlign: 'center', padding: '12px 0', color: 'var(--text-dim)', fontSize: 12 }}>
            Loading…
          </div>
        )}
      </div>
    </div>
  )
}

const uqS: Record<string, CSSProperties> = {
  root: { display: 'flex', flexDirection: 'column', height: '100vh', background: 'var(--bg)', fontFamily: 'var(--sans)' },
  topbar: {
    minHeight: 56, display: 'flex', alignItems: 'center', gap: 10,
    justifyContent: 'space-between',
    padding: '0 24px', borderBottom: '1px solid var(--border)',
    flexShrink: 0, background: 'var(--surface)',
  },
  title: {
    fontSize: 11, fontWeight: 600, color: 'var(--text-muted)',
    fontFamily: 'var(--mono)', textTransform: 'uppercase', letterSpacing: '0.1em',
  },
  badge: {
    background: 'var(--surface3)', color: 'var(--text-muted)',
    borderRadius: 9999, fontSize: 10.5, fontWeight: 600,
    padding: '2px 9px', fontFamily: 'var(--mono)',
    border: '1px solid var(--border)', letterSpacing: '0.04em',
  },
  searchWrap: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
    width: 260,
    maxWidth: '42%',
    background: 'var(--bg)',
    border: '1px solid var(--border)',
    borderRadius: 7,
    padding: '6px 10px',
  },
  filtersBar: {
    display: 'flex',
    alignItems: 'center',
    gap: 10,
    padding: '10px 24px',
    borderBottom: '1px solid var(--border)',
    background: 'var(--surface)',
    flexShrink: 0,
  },
  filterLabel: {
    fontSize: 10.5,
    color: 'var(--text-muted)',
    fontFamily: 'var(--mono)',
    textTransform: 'uppercase',
    letterSpacing: '0.08em',
  },
  filterSelect: {
    minWidth: 220,
    maxWidth: '100%',
    background: 'var(--bg)',
    border: '1px solid var(--border)',
    borderRadius: 7,
    color: 'var(--text)',
    fontSize: 12.5,
    padding: '6px 10px',
    outline: 'none',
  },
  searchInput: {
    flex: 1,
    background: 'none',
    border: 'none',
    outline: 'none',
    color: 'var(--text)',
    fontSize: 12.5,
  },
  clearBtn: {
    background: 'none',
    border: 'none',
    color: 'var(--text-dim)',
    cursor: 'pointer',
    fontSize: 12,
    padding: '0 2px',
  },
  list: { flex: 1, overflowY: 'auto', padding: '20px 24px', display: 'flex', flexDirection: 'column', gap: 14 },
  loadMoreBtn: {
    background: 'var(--surface2)',
    border: '1px solid var(--border)',
    borderRadius: 8,
    padding: '10px 24px',
    color: 'var(--text)',
    fontSize: 13,
    cursor: 'pointer',
    fontFamily: 'var(--sans)',
    fontWeight: 500,
    transition: 'background 0.15s',
  },
  empty: { flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', paddingTop: '18vh' },
  card: {
    background: 'var(--bg)',
    border: '1px solid var(--border)',
    borderRadius: 10,
    padding: '20px',
    transition: 'border-color 0.15s, box-shadow 0.15s',
  },
  cardLead: {
    background: 'var(--surface)',
    borderColor: 'var(--border-med)',
    boxShadow: 'rgba(0,0,0,0.02) 0px 0px 16px, rgba(0,0,0,0.008) 0px 0px 8px',
  },
  cardHeader: { display: 'flex', alignItems: 'flex-start', gap: 14, marginBottom: 14 },
  unkAvatar: {
    width: 36, height: 36, borderRadius: '50%',
    border: '1.5px dashed rgba(38,37,30,0.25)',
    background: 'var(--surface2)',
    flexShrink: 0, display: 'flex', alignItems: 'center', justifyContent: 'center',
    color: 'var(--text-muted)', fontSize: 16, fontWeight: 500,
    fontFamily: 'var(--serif)',
  },
  cardLabel: { fontSize: 14, fontWeight: 500, color: 'var(--text)', letterSpacing: '-0.005em' },
  cardSession: {
    fontSize: 11, color: 'var(--text-muted)',
    fontFamily: 'var(--mono)', textTransform: 'uppercase', letterSpacing: '0.06em',
  },
  cardMeta: { fontSize: 10.5, color: 'var(--text-muted)', fontFamily: 'var(--mono)', marginTop: 4, letterSpacing: '0.04em' },
  cardDur: { fontSize: 12.5, fontWeight: 600, color: 'var(--text)', fontFamily: 'var(--mono)' },
  cardFrags: { fontSize: 10, color: 'var(--text-muted)', fontFamily: 'var(--mono)', marginTop: 2, letterSpacing: '0.04em' },
  quote: {
    display: 'flex', gap: 14, marginBottom: 18,
    background: 'var(--surface2)', borderRadius: 8,
    padding: '13px 16px', border: '1px solid var(--border)',
  },
  quoteBar: { width: 2, flexShrink: 0, background: 'var(--accent)', borderRadius: 1, opacity: 0.55 },
  quoteText: {
    fontSize: 14.5, color: 'var(--text)', lineHeight: 1.55,
    fontFamily: 'var(--serif)', fontStyle: 'italic', fontFeatureSettings: '"cswh"',
  },
  actions: { display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 8 },
  whoLabel: {
    fontSize: 10.5, color: 'var(--text-muted)',
    fontFamily: 'var(--mono)', textTransform: 'uppercase', letterSpacing: '0.08em',
    marginRight: 2,
  },
  candidatePill: {
    display: 'inline-flex', alignItems: 'center', gap: 6,
    padding: '5px 11px 5px 6px',
    background: 'var(--surface3)', border: '1px solid var(--border)',
    borderRadius: 9999, fontSize: 13, fontWeight: 500, cursor: 'pointer',
    transition: 'background 0.15s, color 0.15s', color: 'var(--text)',
  },
  newBtn: {
    background: 'transparent', border: '1px solid var(--border)',
    color: 'var(--text-muted)', borderRadius: 9999,
    padding: '5px 12px', fontSize: 12.5, cursor: 'pointer',
    transition: 'color 0.15s, border-color 0.15s',
  },
  newContactInput: {
    background: 'var(--bg)', border: '1px solid var(--border-med)',
    borderRadius: 6, color: 'var(--text)', fontSize: 12.5, padding: '5px 10px', outline: 'none',
  },
  saveBtn: {
    background: 'var(--surface2)', border: '1px solid var(--border)',
    color: 'var(--text)', borderRadius: 6, padding: '5px 12px', fontSize: 12.5, cursor: 'pointer', fontWeight: 500,
  },
  pickerWrap: { position: 'relative', display: 'flex', flexDirection: 'column', gap: 4 },
  pickerList: {
    position: 'absolute', top: '100%', left: 0, marginTop: 4, zIndex: 50,
    background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 8,
    minWidth: 200, maxHeight: 220, overflowY: 'auto', padding: 4,
    boxShadow: 'rgba(0,0,0,0.08) 0px 4px 16px',
  },
  pickerItem: {
    width: '100%', display: 'flex', alignItems: 'center', gap: 8,
    padding: '6px 8px', background: 'transparent', border: 'none',
    borderRadius: 6, cursor: 'pointer', color: 'var(--text)', fontSize: 12.5, textAlign: 'left',
  },
  pickerEmpty: { padding: '8px 10px', fontSize: 12, color: 'var(--text-dim)' },
  skipBtn: {
    background: 'none', border: 'none', color: 'var(--text-dim)',
    fontSize: 12.5, cursor: 'pointer', padding: '5px 8px', marginLeft: 'auto',
  },
}
