import { startTransition, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { CSSProperties } from 'react'
import { useTranslation } from 'react-i18next'
import { useContactsData } from '../query/contacts'
import { useSessionUtterancesQuery, useSessionsListQuery, useDeleteUtteranceMutation } from '../query/sessions'
import { updateSession } from '../api/sessions'
import { queryKeys } from '../query/keys'
import { useQueryClient } from '@tanstack/react-query'
import { Avatar } from './shared/Avatar'
import { highlight } from '../utils/highlight'

export function AllSessions() {
  const { t } = useTranslation()
  const { contactById } = useContactsData()
  const queryClient = useQueryClient()
  const sessionsQuery = useSessionsListQuery()
  const [selected, setSelected] = useState<string | null>(null)
  const [editing, setEditing] = useState<string | null>(null)
  const [titles, setTitles] = useState<Record<string, string>>({})
  const [searchText, setSearchText] = useState('')
  const dropdownRef = useRef<HTMLDivElement>(null)
  const [exportFormat, setExportFormat] = useState<'json' | 'md' | 'csv'>(() => {
    try { return (localStorage.getItem('vd-export-format') as 'json' | 'md' | 'csv') || 'json' } catch { return 'json' }
  })
  const [exportDropdownOpen, setExportDropdownOpen] = useState(false)
  const editingSince = useRef(0)

  const sessions = sessionsQuery.data ?? []
  const isLoading = sessionsQuery.isLoading

  const effectiveSelected = useMemo(() => {
    if (sessions.length === 0) return null
    if (selected && sessions.some((s) => s.id === selected)) return selected
    return sessions[0]?.id ?? null
  }, [sessions, selected])

  const utterancesQuery = useSessionUtterancesQuery(effectiveSelected)
  const utterances = utterancesQuery.data ?? []
  const session = sessions.find((item) => item.id === effectiveSelected) ?? null
  const filteredUtterances = utterances.filter(
    (utterance) =>
      !searchText ||
      utterance.text.toLowerCase().includes(searchText.toLowerCase()),
  )

  const deleteMutation = useDeleteUtteranceMutation(effectiveSelected)
  const deletingRef = useRef<Set<string>>(new Set())
  const [deletingIds, setDeletingIds] = useState<Set<string>>(new Set())
  const handleDelete = useCallback(
    async (uttId: string) => {
      if (deletingRef.current.has(uttId)) return
      deletingRef.current.add(uttId)
      setDeletingIds(new Set(deletingRef.current))
      try {
        await deleteMutation.mutateAsync(uttId)
      } finally {
        deletingRef.current.delete(uttId)
        setDeletingIds(new Set(deletingRef.current))
      }
    },
    [deleteMutation],
  )

  useEffect(() => {
    if (!exportDropdownOpen) return
    const handler = (e: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
        setExportDropdownOpen(false)
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [exportDropdownOpen])

  const doExport = (fmt?: 'json' | 'md' | 'csv') => {
    if (!session) return
    const format = fmt || exportFormat
    const rows = filteredUtterances.map((u, i) => ({
      time: u.time,
      speaker: contactById(u.speakerId)?.name || 'unknown',
      text: u.text,
      lang: u.lang || '',
      num: i + 1,
    }))
    const title = (titles[session.id] ?? session.title) || t('common.noTitle')
    const date = session.date
    const header = `${title} — ${date}`

    let content: string; let mime: string; let ext: string

    if (format === 'json') {
      content = JSON.stringify(rows.map(r => ({time:r.time, speaker:r.speaker, text:r.text, lang:r.lang})), null, 2)
      mime = 'application/json'; ext = 'json'
    } else if (format === 'md') {
      const lines = [`# ${header}`, '', '| # | Time | Speaker | Text |', '|---|---|---|---|']
      for (const r of rows) lines.push(`| ${r.num} | ${r.time} | ${r.speaker} | ${r.text.replace(/\|/g, '\\|')} |`)
      content = lines.join('\n')
      mime = 'text/markdown'; ext = 'md'
    } else {
      const esc = (v: string) => `"${v.replace(/"/g, '""')}"`
      content = 'time,speaker,text,lang\n'
      for (const r of rows) content += `${esc(r.time)},${esc(r.speaker)},${esc(r.text)},${esc(r.lang)}\n`
      mime = 'text/csv'; ext = 'csv'
    }

    const safeTitle = title.replace(/[^a-zA-Z0-9\u0400-\u04FF_-]+/g, '_').slice(0, 40) || 'session'
    const blob = new Blob([content], { type: `${mime};charset=utf-8` })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url; a.download = `${safeTitle}.${ext}`; a.click()
    URL.revokeObjectURL(url)
  }

  const setFormatAndClose = (fmt: 'json' | 'md' | 'csv') => {
    setExportFormat(fmt)
    try { localStorage.setItem('vd-export-format', fmt) } catch {}
    setExportDropdownOpen(false)
  }

  return (
    <div style={asS.root}>
      <div style={asS.list}>
        <div style={asS.listHeader}>
          <span style={asS.listTitle}>{t('allSessions.title')}</span>
          <span style={asS.listCount}>{sessions.length}</span>
        </div>
        {isLoading && (
          <>
            {[0, 1, 2, 3, 4].map((i) => (
              <div key={i} style={{ ...asS.card, pointerEvents: 'none' }}>
                <div style={asS.skeletonLine} />
                <div style={{ ...asS.skeletonLine, width: '65%' }} />
                <div style={{ ...asS.skeletonLine, width: '40%' }} />
              </div>
            ))}
          </>
        )}
        {!isLoading && sessions.length === 0 && (
          <div style={{ padding: '24px 18px', color: 'var(--text-dim)', fontSize: 13 }}>
            {t('allSessions.empty')}
          </div>
        )}
        {sessions.map((item) => {
          const active = item.id === effectiveSelected
          const speakers = item.speakers
            .map((speakerId) => contactById(speakerId))
            .filter((contact): contact is NonNullable<typeof contact> => contact !== null)

          return (
            <div
              key={item.id}
              data-testid={`session-card-${item.id}`}
              onClick={() => setSelected(item.id)}
              style={{ ...asS.card, ...(active ? asS.cardActive : {}) }}
            >
              {active && <div style={asS.cardLine} />}
              <div style={asS.cardTop}>
                <div
                  style={{
                    ...asS.cardTitle,
                    ...((titles[item.id] ?? item.title) === t('common.noTitle') ? asS.cardTitleEmpty : {}),
                  }}
                  onDoubleClick={(e) => {
                    e.stopPropagation()
                    editingSince.current = Date.now()
                    setEditing(item.id)
                  }}
                >
                  {(titles[item.id] ?? (item.title || t('common.noTitle')))}
                </div>
                <div style={asS.cardMeta}>
                  {item.date} · {item.time}
                </div>
              </div>
              <div style={asS.cardRow}>
                <div style={{ display: 'flex' }}>
                  {speakers.slice(0, 4).map((contact, index) => (
                    <div
                      key={contact.id}
                      style={{
                        width: 19,
                        height: 19,
                        borderRadius: '50%',
                        background: `${contact.color}18`,
                        border: `1.5px solid ${contact.color}55`,
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        fontSize: 7,
                        fontWeight: 700,
                        color: contact.color,
                        marginLeft: index ? -5 : 0,
                        fontFamily: 'var(--mono)',
                      }}
                    >
                      {contact.initials}
                    </div>
                  ))}
                  {item.speakers.length > 4 && (
                    <div
                      style={{
                        width: 19,
                        height: 19,
                        borderRadius: '50%',
                        background: 'var(--surface3)',
                        border: '1.5px solid var(--border)',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        fontSize: 8,
                        color: 'var(--text-dim)',
                        marginLeft: -5,
                        fontFamily: 'var(--mono)',
                      }}
                    >
                      +{item.speakers.length - 4}
                    </div>
                  )}
                </div>
                <div style={{ display: 'flex', gap: 6, marginLeft: 'auto' }}>
                  {item.duration && <span style={asS.tag}>{item.duration}</span>}
                  <span style={asS.tag}>{t('allSessions.tagReplies', { count: item.utteranceCount })}</span>
                  {item.languages.map((language) => (
                    <span key={language} style={asS.langPill}>
                      {language}
                    </span>
                  ))}
                </div>
              </div>
              {item.preview && <div style={asS.cardPreview}>{item.preview}</div>}
            </div>
          )
        })}
      </div>

      <div style={asS.transcript}>
        {session ? (
          <>
            <div style={asS.transcriptHeader}>
              <div>
                {editing === session.id ? (
                  <input
                    autoFocus
                    data-testid="session-title-input"
                    defaultValue={titles[session.id] ?? session.title}
                    style={asS.titleInput}
                    onBlur={async (e) => {
                      if (Date.now() - editingSince.current < 100) return
                      const value = e.target.value.trim() || ''
                      setTitles((current) => ({ ...current, [session.id]: value }))
                      setEditing(null)
                      try { await updateSession(session.id, { title: value }) } catch {}
                      queryClient.invalidateQueries({ queryKey: queryKeys.sessions.list() })
                    }}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') (e.target as HTMLInputElement).blur()
                    }}
                  />
                ) : (
                  <div
                    data-testid="session-title"
                    style={{
                      ...asS.transcriptTitle,
                      ...((titles[session.id] ?? session.title) === t('common.noTitle') ? asS.cardTitleEmpty : {}),
                    }}
                    onDoubleClick={() => {
                      editingSince.current = Date.now()
                      setEditing(session.id)
                    }}
                  >
                    {(titles[session.id] ?? session.title) || t('common.noTitle')}
                  </div>
                )}
                <div style={asS.transcriptMeta}>
                  {session.date} · {session.time}{session.duration ? ` · ${session.duration}` : ''}
                </div>
              </div>
              <div style={asS.searchBox}>
                <span style={{ color: 'var(--text-dim)', fontSize: 13 }}>⌕</span>
                <input
                  data-testid="transcript-search"
                  placeholder={t('allSessions.searchPlaceholder')}
                  value={searchText}
                  onChange={(e) => startTransition(() => setSearchText(e.target.value))}
                  style={asS.searchInput}
                />
              </div>
              <div ref={dropdownRef} style={{ position: 'relative' }}>
                <div style={{ display: 'flex' }}>
                  <button
                    onClick={() => doExport()}
                    disabled={filteredUtterances.length === 0}
                    data-testid="export-btn"
                    style={asS.exportBtn}
                  >
                    {exportFormat === 'json' ? t('allSessions.exportJson')
                      : exportFormat === 'md' ? t('allSessions.exportMd')
                      : t('allSessions.exportCsv')}
                  </button>
                  <button
                    onClick={() => setExportDropdownOpen((prev) => !prev)}
                    disabled={filteredUtterances.length === 0}
                    data-testid="export-dropdown-toggle"
                    style={asS.exportDropdownToggle}
                  >
                    ▾
                  </button>
                </div>
                {exportDropdownOpen && (
                  <div style={asS.exportMenu}>
                    {(['json', 'md', 'csv'] as const).map((fmt) => (
                      <button
                        key={fmt}
                        onClick={() => { setFormatAndClose(fmt); doExport(fmt) }}
                        data-testid={`export-option-${fmt}`}
                        style={{
                          ...asS.exportMenuItem,
                          ...(exportFormat === fmt ? asS.exportMenuItemActive : {}),
                        }}
                      >
                        {fmt === 'json' ? t('allSessions.exportJson')
                          : fmt === 'md' ? t('allSessions.exportMd')
                          : t('allSessions.exportCsv')}
                      </button>
                    ))}
                  </div>
                )}
              </div>
            </div>
            <div style={asS.transcriptBody}>
              {filteredUtterances.map((utterance) => {
                const contact = contactById(utterance.speakerId)
                const hit =
                  searchText &&
                  utterance.text.toLowerCase().includes(searchText.toLowerCase())

                return (
                  <div
                    key={utterance.id}
                    data-testid={`transcript-utt-${utterance.id}`}
                    style={{
                      ...asS.uttRow,
                      background: hit ? 'rgba(245,78,0,0.05)' : 'transparent',
                    }}
                  >
                    <Avatar contact={contact} size={26} />
                    <div style={{ flex: 1 }}>
                      <div
                        style={{
                          display: 'flex',
                          gap: 8,
                          alignItems: 'center',
                          marginBottom: 3,
                        }}
                      >
                        <span
                          style={{
                            fontSize: 12.5,
                            fontWeight: 600,
                            color: contact ? contact.color : 'var(--text-dim)',
                            cursor: 'pointer',
                          }}
                        >
                          {contact ? contact.name : t('common.unknown')}
                        </span>
                        <span
                          style={{
                            fontSize: 10.5,
                            color: 'var(--text-dim)',
                            fontFamily: 'var(--mono)',
                          }}
                        >
                          {utterance.time}
                        </span>
                        {utterance.lang && <span style={asS.langTag}>{utterance.lang}</span>}
                        <button
                          data-testid={`delete-utt-${utterance.id}`}
                          onClick={(e) => { e.stopPropagation(); void handleDelete(utterance.id) }}
                          disabled={deletingIds.has(utterance.id)}
                          style={{
                            ...asS.deleteBtn,
                            opacity: deletingIds.has(utterance.id) ? 0.15 : 0.3,
                            cursor: deletingIds.has(utterance.id) ? 'default' : 'pointer',
                          }}
                        >
                          ✕
                        </button>
                      </div>
                      <div
                        style={{
                          fontSize: 13.5,
                          color: 'var(--text)',
                          lineHeight: 1.55,
                          fontFamily: 'var(--utterance-font,var(--sans))',
                        }}
                      >
                        {searchText ? highlight(utterance.text, searchText) : utterance.text}
                      </div>
                    </div>
                  </div>
                )
              })}
              {!utterancesQuery.isLoading && utterances.length === 0 && (
                <div data-testid="no-utterances" style={{ color: 'var(--text-dim)', fontSize: 13, padding: '16px 0' }}>
                  {t('allSessions.noUtterances')}
                </div>
              )}
            </div>
          </>
        ) : (
          <div
            style={{
              flex: 1,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              color: 'var(--text-dim)',
              fontSize: 14,
            }}
          >
            {t('allSessions.selectSession')}
          </div>
        )}
      </div>
    </div>
  )
}

const asS: Record<string, CSSProperties> = {
  root: { display: 'flex', height: '100vh', background: 'var(--bg)', fontFamily: 'var(--sans)' },
  list: {
    width: 308,
    borderRight: '1px solid var(--border)',
    overflowY: 'auto',
    contentVisibility: 'auto',
    flexShrink: 0,
    background: 'var(--surface)',
  },
  listHeader: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
    padding: '16px 18px 12px',
    borderBottom: '1px solid var(--border)',
    position: 'sticky',
    top: 0,
    background: 'var(--surface)',
    zIndex: 1,
  },
  listTitle: { fontSize: 14.5, fontWeight: 600, color: 'var(--text)' },
  listCount: {
    background: 'var(--surface2)',
    color: 'var(--text-muted)',
    borderRadius: 9999,
    fontSize: 11,
    fontWeight: 600,
    padding: '1px 7px',
    fontFamily: 'var(--mono)',
  },
  card: {
    padding: '13px 18px',
    borderBottom: '1px solid var(--border)',
    cursor: 'pointer',
    transition: 'background 0.1s',
    position: 'relative',
  },
  cardActive: { background: 'rgba(38,37,30,0.04)' },
  cardLine: {
    position: 'absolute',
    left: 0,
    top: '15%',
    bottom: '15%',
    width: 2,
    background: 'var(--accent)',
    borderRadius: 1,
  },
  cardTop: { marginBottom: 7 },
  cardTitle: {
    fontSize: 13,
    fontWeight: 600,
    color: 'var(--text)',
    lineHeight: 1.3,
    marginBottom: 2,
    cursor: 'pointer',
  },
  cardTitleEmpty: {
    border: '1px dashed var(--border-str)',
    borderRadius: 6,
    padding: '4px 8px',
    color: 'var(--text-soft)',
    background: 'var(--surface2)',
    fontWeight: 500,
    fontStyle: 'italic',
  },
  cardMeta: { fontSize: 10.5, color: 'var(--text-dim)', fontFamily: 'var(--mono)' },
  cardRow: { display: 'flex', alignItems: 'center', gap: 6, marginBottom: 5 },
  tag: {
    fontSize: 10,
    color: 'var(--text-dim)',
    fontFamily: 'var(--mono)',
    background: 'var(--surface2)',
    borderRadius: 4,
    padding: '2px 6px',
  },
  langPill: {
    fontSize: 10,
    fontWeight: 600,
    color: 'var(--accent)',
    background: 'rgba(245,78,0,0.08)',
    borderRadius: 9999,
    padding: '2px 7px',
    fontFamily: 'var(--mono)',
  },
  cardPreview: {
    fontSize: 12,
    color: 'var(--text-dim)',
    whiteSpace: 'nowrap',
    overflow: 'hidden',
    textOverflow: 'ellipsis',
  },
  titleInput: {
    background: 'var(--bg)',
    border: '1px solid var(--accent)',
    borderRadius: 4,
    color: 'var(--text)',
    fontSize: 13,
    fontWeight: 600,
    padding: '2px 6px',
    outline: 'none',
    width: '100%',
  },
  transcript: { flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' },
  transcriptHeader: {
    padding: '14px 24px',
    borderBottom: '1px solid var(--border)',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    flexShrink: 0,
    background: 'var(--surface)',
  },
  transcriptTitle: { fontSize: 14.5, fontWeight: 600, color: 'var(--text)', marginBottom: 2, cursor: 'pointer' },
  transcriptMeta: { fontSize: 11, color: 'var(--text-dim)', fontFamily: 'var(--mono)' },
  searchBox: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
    background: 'var(--bg)',
    border: '1px solid var(--border)',
    borderRadius: 7,
    padding: '6px 12px',
  },
  searchInput: {
    background: 'none',
    border: 'none',
    outline: 'none',
    color: 'var(--text)',
    fontSize: 13,
    width: 180,
  },
  transcriptBody: {
    flex: 1,
    overflowY: 'auto',
    padding: '12px 24px',
    display: 'flex',
    flexDirection: 'column',
    gap: 0,
  },
  uttRow: {
    display: 'flex',
    gap: 10,
    padding: '10px 8px',
    borderRadius: 6,
    borderBottom: '1px solid var(--border)',
  },
  langTag: {
    fontSize: 9.5,
    fontFamily: 'var(--mono)',
    fontWeight: 700,
    padding: '1px 5px',
    background: 'var(--surface2)',
    color: 'var(--accent)',
    borderRadius: 3,
  },
  deleteBtn: {
    fontSize: 12,
    background: 'none',
    border: 'none',
    color: 'var(--text-muted)',
    fontFamily: 'var(--mono)',
    padding: '1px 5px',
    transition: 'opacity 0.15s',
  },
  skeletonLine: {
    height: 10,
    borderRadius: 4,
    background: 'var(--surface2)',
    marginBottom: 6,
    animation: 'pulse 1.4s ease-in-out infinite',
  },
  exportBtn: {
    background: 'var(--surface2)',
    border: '1px solid var(--border)',
    borderRight: 'none',
    borderRadius: '6px 0 0 6px',
    color: 'var(--text)',
    fontSize: 12,
    fontFamily: 'var(--sans)',
    padding: '6px 14px',
    cursor: 'pointer',
    fontWeight: 500,
    whiteSpace: 'nowrap',
  },
  exportDropdownToggle: {
    background: 'var(--surface2)',
    border: '1px solid var(--border)',
    borderRadius: '0 6px 6px 0',
    color: 'var(--text)',
    fontSize: 11,
    fontFamily: 'var(--sans)',
    padding: '6px 8px',
    cursor: 'pointer',
  },
  exportMenu: {
    position: 'absolute',
    top: '100%',
    right: 0,
    marginTop: 4,
    background: 'var(--bg)',
    border: '1px solid var(--border)',
    borderRadius: 8,
    boxShadow: 'rgba(0,0,0,0.1) 0px 4px 16px',
    zIndex: 20,
    padding: 4,
    minWidth: 140,
    display: 'flex',
    flexDirection: 'column',
  },
  exportMenuItem: {
    background: 'none',
    border: 'none',
    borderRadius: 5,
    color: 'var(--text)',
    fontSize: 12,
    fontFamily: 'var(--sans)',
    padding: '7px 12px',
    cursor: 'pointer',
    textAlign: 'left',
  },
  exportMenuItemActive: {
    background: 'var(--surface2)',
    fontWeight: 500,
    color: 'var(--accent)',
  },
}
