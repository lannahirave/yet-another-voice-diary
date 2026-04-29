import { useEffect, useRef, useState } from 'react'
import type { CSSProperties } from 'react'
import { useTranslation } from 'react-i18next'
import { useSearchResultsQuery } from '../query/search'
import type { ApiSearchHit } from '../types/api'
import { highlight } from '../utils/highlight'

export function Search() {
  const { t } = useTranslation()
  const [query, setQuery] = useState('')
  const [debouncedQuery, setDebouncedQuery] = useState('')
  const [langFilter, setLangFilter] = useState<string[]>([])
  const debounceRef = useRef<number | null>(null)

  useEffect(() => {
    if (debounceRef.current !== null) window.clearTimeout(debounceRef.current)
    debounceRef.current = window.setTimeout(() => setDebouncedQuery(query), 300)
    return () => {
      if (debounceRef.current !== null) window.clearTimeout(debounceRef.current)
    }
  }, [query])

  const language = langFilter.length === 1 ? langFilter[0] : undefined
  const searchQuery = useSearchResultsQuery(debouncedQuery, { language, limit: 100 })

  const hits = searchQuery.data?.hits ?? []
  const total = searchQuery.data?.total ?? 0
  const error = searchQuery.error ? t('search.backendUnavailable') : null

  const toggleLanguage = (value: string) =>
    setLangFilter((current) => (
      current.includes(value)
        ? current.filter((item) => item !== value)
        : [...current, value]
    ))

  const grouped = hits.reduce<Record<string, { title: string; items: ApiSearchHit[] }>>(
    (acc, hit) => {
      if (!acc[hit.session_id]) {
        acc[hit.session_id] = { title: hit.session_title || hit.session_id, items: [] }
      }
      acc[hit.session_id].items.push(hit)
      return acc
    },
    {},
  )

  function msToTime(ms: number): string {
    const s = Math.floor(ms / 1000)
    const m = Math.floor(s / 60)
    return `${m}:${String(s % 60).padStart(2, '0')}`
  }

  return (
    <div style={srS.root}>
      <div style={srS.topbar}>
        <div style={srS.searchWrap}>
          <span style={{ color: 'var(--text-dim)', fontSize: 15 }}>⌕</span>
          <input
            autoFocus
            data-testid="search-input"
            placeholder={t('search.placeholder')}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            style={srS.searchInput}
          />
          {query && (
            <button onClick={() => setQuery('')} style={srS.clearBtn}>
              ✕
            </button>
          )}
        </div>
      </div>

      <div style={srS.filtersBar}>
        <div style={srS.filterGroup}>
          <span style={srS.filterLabel}>{t('search.languageLabel')}</span>
          {['UK', 'EN'].map((value) => (
            <button
              key={value}
              data-testid={`lang-filter-${value.toLowerCase()}`}
              onClick={() => toggleLanguage(value)}
              style={{
                ...srS.filterPill,
                ...(langFilter.includes(value)
                  ? {
                      background: 'rgba(245,78,0,0.1)',
                      borderColor: 'rgba(245,78,0,0.35)',
                      color: 'var(--accent)',
                    }
                  : {}),
              }}
            >
              {value}
            </button>
          ))}
        </div>
        {debouncedQuery.trim() && (
          <div style={{ marginLeft: 'auto', fontSize: 11, color: 'var(--text-dim)', fontFamily: 'var(--mono)', alignSelf: 'center' }}>
            {t('search.results', { count: total })}
          </div>
        )}
      </div>

      <div style={srS.results}>
        {error && <div style={srS.empty}>{error}</div>}
        {!error && !debouncedQuery.trim() && <div style={srS.empty}>{t('search.emptyHint')}</div>}
        {!error && debouncedQuery.trim() && Object.keys(grouped).length === 0 && (
          <div style={srS.empty}>{t('search.emptyNothing')}</div>
        )}

        {Object.entries(grouped).map(([sessionId, { title, items }]) => (
          <div key={sessionId} data-testid={`search-group-${sessionId}`} style={srS.group}>
            <div style={srS.groupHeader}>
              <span style={srS.groupTitle}>{title || t('common.noTitle')}</span>
              <span style={srS.groupCount}>{t('search.matches', { count: items.length })}</span>
            </div>
            {items.map((hit: ApiSearchHit) => (
              <div key={hit.utterance_id} data-testid={`search-result-${hit.utterance_id}`} style={srS.resultRow}>
                <div style={{ flex: 1 }}>
                  <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 3 }}>
                    <span style={{ fontSize: 10.5, color: 'var(--text-dim)', fontFamily: 'var(--mono)' }}>
                      {msToTime(hit.started_ms)}
                    </span>
                    {hit.language && (
                      <span style={{ fontSize: 9.5, fontFamily: 'var(--mono)', fontWeight: 700, padding: '1px 5px', background: 'var(--surface2)', color: 'var(--accent)', borderRadius: 3 }}>
                        {hit.language}
                      </span>
                    )}
                  </div>
                  <div style={{ fontSize: 13.5, color: 'var(--text)', lineHeight: 1.55, fontFamily: 'var(--utterance-font,var(--sans))' }}>
                    {debouncedQuery.trim()
                      ? highlight(hit.transcript, debouncedQuery.trim())
                      : hit.snippet || hit.transcript}
                  </div>
                </div>
              </div>
            ))}
          </div>
        ))}
      </div>
    </div>
  )
}

const srS: Record<string, CSSProperties> = {
  root: { display: 'flex', flexDirection: 'column', height: '100vh', background: 'var(--bg)', fontFamily: 'var(--sans)' },
  topbar: { padding: '14px 22px', borderBottom: '1px solid var(--border)', background: 'var(--surface)', flexShrink: 0 },
  searchWrap: {
    display: 'flex',
    alignItems: 'center',
    gap: 10,
    background: 'var(--bg)',
    border: '1px solid var(--border-med)',
    borderRadius: 8,
    padding: '9px 14px',
  },
  searchInput: { flex: 1, background: 'none', border: 'none', outline: 'none', color: 'var(--text)', fontSize: 14 },
  clearBtn: { background: 'none', border: 'none', color: 'var(--text-dim)', cursor: 'pointer', fontSize: 12, padding: '0 2px' },
  filtersBar: {
    display: 'flex',
    flexWrap: 'wrap',
    gap: 14,
    padding: '10px 22px',
    borderBottom: '1px solid var(--border)',
    background: 'var(--surface)',
    flexShrink: 0,
    alignItems: 'center',
  },
  filterGroup: { display: 'flex', alignItems: 'center', gap: 5 },
  filterLabel: { fontSize: 11, color: 'var(--text-dim)', fontFamily: 'var(--mono)', marginRight: 3 },
  filterPill: {
    background: 'var(--surface2)',
    border: '1px solid var(--border)',
    color: 'var(--text-muted)',
    borderRadius: 9999,
    padding: '3px 10px',
    fontSize: 12,
    cursor: 'pointer',
    transition: 'all 0.1s',
  },
  results: { flex: 1, overflowY: 'auto', padding: '14px 22px', display: 'flex', flexDirection: 'column', gap: 14 },
  empty: { padding: '40px 0', textAlign: 'center', color: 'var(--text-dim)', fontSize: 14 },
  group: { background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 8, overflow: 'hidden' },
  groupHeader: {
    display: 'flex',
    alignItems: 'center',
    gap: 10,
    padding: '10px 14px',
    borderBottom: '1px solid var(--border)',
    background: 'var(--surface2)',
  },
  groupTitle: { fontSize: 13, fontWeight: 500, color: 'var(--text)', flex: 1 },
  groupCount: { fontSize: 10.5, background: 'rgba(245,78,0,0.1)', color: 'var(--accent)', borderRadius: 9999, padding: '2px 8px', fontFamily: 'var(--mono)' },
  resultRow: { display: 'flex', gap: 10, padding: '11px 14px', borderBottom: '1px solid var(--border)' },
}
