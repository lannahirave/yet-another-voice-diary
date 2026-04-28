import type { CSSProperties } from 'react'
import { useTranslation } from 'react-i18next'
import { useQueueCountQuery } from '../query/queue'
import type { ScreenId } from '../types/domain'

interface SidebarProps {
  screen: ScreenId
  setScreen: (s: ScreenId) => void
  recording: boolean
}

interface NavItem {
  id: ScreenId
  label: string
  icon: string
  badge?: number
}

interface NavGroup {
  group: string
  items: NavItem[]
}

export function Sidebar({ screen, setScreen, recording }: SidebarProps) {
  const { t } = useTranslation()
  const countQuery = useQueueCountQuery()
  const unknownCount = countQuery.data ?? 0

  const nav: NavGroup[] = [
    {
      group: t('sidebar.groupRecords'),
      items: [
        { id: 'session', label: t('sidebar.currentSession'), icon: '◎' },
        { id: 'sessions', label: t('sidebar.allSessions'), icon: '≡' },
      ],
    },
    {
      group: t('sidebar.groupPeople'),
      items: [
        { id: 'contacts', label: t('sidebar.contacts'), icon: '◯' },
        { id: 'queue', label: t('sidebar.queue'), icon: '?', badge: unknownCount },
      ],
    },
    {
      group: t('sidebar.groupTools'),
      items: [
        { id: 'search', label: t('sidebar.search'), icon: '⌕' },
        { id: 'settings', label: t('sidebar.settings'), icon: '◈' },
      ],
    },
  ]

  return (
    <div style={sbS.root}>
      <div style={sbS.header}>
        <div style={sbS.appName}>Voice Diary</div>
        <div style={sbS.appSub}>{t('sidebar.sessionsToday', { count: 3 })}</div>
      </div>

      <nav style={{ flex: 1, overflow: 'auto' }}>
        {nav.map((group) => (
          <div key={group.group} style={sbS.group}>
            <div style={sbS.groupLabel}>{group.group}</div>
            {group.items.map((item) => {
              const active = screen === item.id
              return (
                <button
                  key={item.id}
                  onClick={() => setScreen(item.id)}
                  style={{ ...sbS.navItem, ...(active ? sbS.navItemActive : {}) }}
                >
                  <span
                    style={{
                      ...sbS.navIcon,
                      color: active ? 'var(--accent)' : 'var(--text-dim)',
                    }}
                  >
                    {item.icon}
                  </span>
                  <span style={{ flex: 1 }}>{item.label}</span>
                  {item.id === 'session' && recording && (
                    <span className="rec-pulse" style={sbS.recordDot} />
                  )}
                  {item.badge !== undefined && item.badge > 0 && (
                    <span style={sbS.badge}>{item.badge}</span>
                  )}
                  {active && <div style={sbS.activeLine} />}
                </button>
              )
            })}
          </div>
        ))}
      </nav>

    </div>
  )
}

const sbS: Record<string, CSSProperties> = {
  root: {
    width: 220,
    minWidth: 220,
    height: '100vh',
    background: 'var(--surface)',
    borderRight: '1px solid var(--border)',
    display: 'flex',
    flexDirection: 'column',
    userSelect: 'none',
    flexShrink: 0,
  },
  header: {
    padding: '22px 20px 18px',
    borderBottom: '1px solid var(--border)',
  },
  appName: {
    fontSize: 15,
    fontWeight: 600,
    color: 'var(--text)',
    letterSpacing: '-0.2px',
  },
  appSub: {
    fontSize: 11,
    color: 'var(--text-dim)',
    marginTop: 3,
    fontFamily: 'var(--mono)',
  },
  group: { padding: '16px 0 4px' },
  groupLabel: {
    fontSize: 9.5,
    fontWeight: 600,
    letterSpacing: '0.12em',
    color: 'var(--text-dim)',
    padding: '0 18px 6px',
    fontFamily: 'var(--mono)',
    textTransform: 'uppercase',
  },
  navItem: {
    width: '100%',
    display: 'flex',
    alignItems: 'center',
    gap: 9,
    padding: '7px 18px',
    background: 'none',
    border: 'none',
    cursor: 'pointer',
    color: 'var(--text-muted)',
    fontSize: 13.5,
    fontWeight: 500,
    position: 'relative',
    textAlign: 'left',
    transition: 'color 0.12s',
    borderRadius: 0,
  },
  navItemActive: {
    color: 'var(--text)',
    background: 'rgba(38,37,30,0.05)',
  },
  navIcon: {
    fontSize: 13,
    width: 16,
    textAlign: 'center',
    transition: 'color 0.12s',
  },
  activeLine: {
    position: 'absolute',
    left: 0,
    top: '20%',
    bottom: '20%',
    width: 2,
    background: 'var(--accent)',
    borderRadius: 1,
  },
  badge: {
    background: 'var(--record)',
    color: '#fff',
    borderRadius: 9999,
    fontSize: 10,
    fontWeight: 700,
    padding: '1px 6px',
    fontFamily: 'var(--mono)',
  },
  recordDot: {
    width: 7,
    height: 7,
    borderRadius: '50%',
    background: 'var(--record)',
    flexShrink: 0,
  },
}
