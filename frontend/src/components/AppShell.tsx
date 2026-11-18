import { useEffect, useRef, useState, type KeyboardEvent, type ReactNode } from 'react'
import { AudioLines, BookOpen, ChevronDown, ChevronRight, Languages, LayoutDashboard, LogOut, Menu, Moon, PanelLeftClose, Settings2, Sun, X } from 'lucide-react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'
import { useTheme } from '../contexts/ThemeContext'
import { Logo } from './Logo'

const SIDEBAR_KEY = 'talkbuddy-sidebar-collapsed'
const navigation = [
  { to: '/overview', label: 'Overview', icon: LayoutDashboard },
  { to: '/translate', label: 'Translate', icon: Languages },
  { to: '/meeting', label: 'Live Meeting', icon: AudioLines },
  { to: '/history', label: 'History', icon: BookOpen },
  { to: '/settings', label: 'Settings', icon: Settings2 },
] as const

function currentPage(pathname: string, hash: string) {
  if (pathname.startsWith('/history')) return pathname === '/history' ? { title: 'History', parent: '' } : { title: 'Session details', parent: 'History' }
  if (pathname === '/settings') return { title: 'Settings', parent: '' }
  if (pathname === '/meeting' || hash === '#meeting') return { title: 'Live Meeting', parent: 'Workspace' }
  if (pathname === '/translate' || hash === '#translate') return { title: 'Translate', parent: 'Workspace' }
  if (pathname === '/workspace') return { title: 'Microphone translation', parent: 'Translate' }
  return { title: 'Overview', parent: '' }
}

function isActive(to: string, pathname: string) {
  if (to === '/translate') return pathname === '/translate' || pathname === '/workspace'
  return pathname === to || (to === '/history' && pathname.startsWith('/history/'))
}

export function AppShell({ children }: { children: ReactNode }) {
  const [collapsed, setCollapsed] = useState(() => {
    try { return window.localStorage.getItem(SIDEBAR_KEY) === 'true' } catch { return false }
  })
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [profileOpen, setProfileOpen] = useState(false)
  const [logoutError, setLogoutError] = useState('')
  const [signingOut, setSigningOut] = useState(false)
  const { user, logout } = useAuth()
  const { theme, toggle } = useTheme()
  const navigate = useNavigate()
  const location = useLocation()
  const drawerRef = useRef<HTMLElement>(null)
  const drawerCloseRef = useRef<HTMLButtonElement>(null)
  const menuTriggerRef = useRef<HTMLButtonElement>(null)
  const profileRef = useRef<HTMLDivElement>(null)
  const mainRef = useRef<HTMLElement>(null)
  const previousRouteRef = useRef(location.pathname + location.hash)
  const page = currentPage(location.pathname, location.hash)

  useEffect(() => {
    try { window.localStorage.setItem(SIDEBAR_KEY, String(collapsed)) } catch { /* storage can be unavailable */ }
  }, [collapsed])

  useEffect(() => {
    const route = location.pathname + location.hash
    if (previousRouteRef.current !== route) {
      setDrawerOpen(false)
      setProfileOpen(false)
      previousRouteRef.current = route
      mainRef.current?.focus({ preventScroll: true })
    }
    if (location.pathname === '/workspace' && (location.hash === '#meeting' || location.hash === '#translate')) {
      const id = location.hash.slice(1)
      const frame = window.requestAnimationFrame(() => {
        const section = document.getElementById(id)
        section?.scrollIntoView?.({ behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth', block: 'start' })
      })
      return () => window.cancelAnimationFrame(frame)
    }
  }, [location.pathname, location.hash])

  useEffect(() => {
    if (!drawerOpen) return
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    drawerCloseRef.current?.focus()
    const closeOnEscape = (event: globalThis.KeyboardEvent) => {
      if (event.key === 'Escape') { event.preventDefault(); setDrawerOpen(false); menuTriggerRef.current?.focus() }
    }
    document.addEventListener('keydown', closeOnEscape)
    return () => { document.body.style.overflow = previousOverflow; document.removeEventListener('keydown', closeOnEscape) }
  }, [drawerOpen])

  useEffect(() => {
    if (!profileOpen) return
    const dismiss = (event: PointerEvent) => { if (!profileRef.current?.contains(event.target as Node)) setProfileOpen(false) }
    const escape = (event: globalThis.KeyboardEvent) => { if (event.key === 'Escape') { setProfileOpen(false); profileRef.current?.querySelector('button')?.focus() } }
    document.addEventListener('pointerdown', dismiss)
    document.addEventListener('keydown', escape)
    return () => { document.removeEventListener('pointerdown', dismiss); document.removeEventListener('keydown', escape) }
  }, [profileOpen])

  const trapDrawerFocus = (event: KeyboardEvent<HTMLElement>) => {
    if (!drawerOpen || event.key !== 'Tab' || window.innerWidth >= 1024) return
    const items = drawerRef.current?.querySelectorAll<HTMLElement>('a[href], button:not([disabled])')
    if (!items?.length) return
    const first = items[0]
    const last = items[items.length - 1]
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus() }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus() }
  }

  const handleLogout = async () => {
    if (signingOut) return
    setSigningOut(true)
    setLogoutError('')
    try { await logout(); setDrawerOpen(false); setProfileOpen(false); navigate('/') }
    catch { setLogoutError('Could not sign out. Please retry.') }
    finally { setSigningOut(false) }
  }

  return <div className="min-h-screen overflow-x-clip bg-canvas text-foreground">
    <div className={`lg:grid lg:min-h-screen ${collapsed ? 'lg:grid-cols-[68px_minmax(0,1fr)]' : 'lg:grid-cols-[228px_minmax(0,1fr)]'} transition-[grid-template-columns] duration-200`}>
      <aside ref={drawerRef} role={drawerOpen ? 'dialog' : undefined} aria-label={drawerOpen ? 'Navigation drawer' : undefined} aria-modal={drawerOpen ? true : undefined} onKeyDown={trapDrawerFocus}
        className={`fixed inset-y-0 left-0 z-40 flex w-[min(84vw,280px)] min-w-0 flex-col overflow-y-auto bg-sidebar transition-[transform,width,visibility] duration-200 lg:sticky lg:top-0 lg:h-screen lg:w-auto lg:translate-x-0 lg:visible ${drawerOpen ? 'visible translate-x-0' : 'invisible -translate-x-full'}`}>
        <div className="flex h-16 shrink-0 items-center justify-between gap-2 px-4">
          <Logo to="/overview" compact={collapsed && !drawerOpen} />
          <button ref={drawerCloseRef} type="button" className="icon-btn lg:hidden" onClick={() => { setDrawerOpen(false); menuTriggerRef.current?.focus() }} aria-label="Close navigation"><X size={18} /></button>
          {!collapsed && <button type="button" className="icon-btn hidden lg:inline-grid" onClick={() => setCollapsed(true)} aria-label="Collapse sidebar" aria-expanded="true" title="Collapse sidebar"><PanelLeftClose size={18} /></button>}
        </div>
        <nav className="flex-1 px-2 py-5" aria-label="Primary navigation">
          {collapsed && <button type="button" className="icon-btn mb-4 hidden w-full lg:inline-grid" onClick={() => setCollapsed(false)} aria-label="Expand sidebar" aria-expanded="false" title="Expand sidebar"><ChevronRight size={18} /></button>}
          {!collapsed && <p className="px-3 pb-2 text-[10px] font-semibold uppercase tracking-[.15em] text-muted">Workspace</p>}
          <ul className="space-y-1">{navigation.map(({ to, label, icon: Icon }) => {
            const active = isActive(to, location.pathname)
            return <li key={to}><Link to={to} aria-current={active ? 'page' : undefined} title={collapsed ? label : undefined} onClick={() => setDrawerOpen(false)} className={`flex h-10 items-center gap-3 rounded-md px-3 text-sm font-medium transition-colors duration-150 ${active ? 'bg-raised text-accent' : 'text-muted hover:bg-raised hover:text-foreground'}`}><Icon size={17} className="shrink-0" aria-hidden="true" /><span className={collapsed && !drawerOpen ? 'lg:sr-only' : ''}>{label}</span></Link></li>
          })}</ul>
        </nav>
        <div className="p-3"><div className="flex items-center gap-2 rounded-md bg-raised px-2 py-2"><span className="grid h-8 w-8 shrink-0 place-items-center rounded-md bg-sidebar text-xs font-semibold text-accent" aria-hidden="true">{user?.name.slice(0, 2).toUpperCase()}</span><div className={`min-w-0 ${collapsed && !drawerOpen ? 'lg:sr-only' : ''}`}><p className="truncate text-xs font-semibold">{user?.name}</p><p className="truncate text-[11px] text-muted">{user?.email}</p></div></div></div>
      </aside>
      {drawerOpen && <button type="button" className="fixed inset-0 z-30 bg-black/65 lg:hidden" aria-label="Close navigation drawer" onClick={() => { setDrawerOpen(false); menuTriggerRef.current?.focus() }} />}
      <div className="min-w-0">
        <header className="flex h-16 min-w-0 items-center justify-between gap-3 bg-sidebar px-4 md:px-6 lg:px-8">
          <div className="flex min-w-0 items-center gap-2"><button ref={menuTriggerRef} type="button" className="icon-btn lg:hidden" aria-label="Open navigation" aria-expanded={drawerOpen} onClick={() => setDrawerOpen(true)}><Menu size={19} /></button><span className="hidden text-xs text-muted sm:inline">TalkBuddy</span><ChevronRight size={14} className="hidden text-muted sm:inline" aria-hidden="true" />{page.parent && <><span className="hidden text-xs text-muted sm:inline">{page.parent}</span><ChevronRight size={14} className="hidden text-muted sm:inline" aria-hidden="true" /></>}<span className="truncate text-sm font-semibold">{page.title}</span></div>
          <div className="flex items-center gap-1"><button type="button" onClick={toggle} className="icon-btn" aria-label={theme === 'dark' ? 'Use light theme' : 'Use dark theme'} title={theme === 'dark' ? 'Use light theme' : 'Use dark theme'}>{theme === 'dark' ? <Sun size={18} /> : <Moon size={18} />}</button>
            <div ref={profileRef} className="relative"><button type="button" className="flex h-9 items-center gap-2 rounded-md px-1.5 text-sm transition-colors duration-150 hover:bg-raised" aria-label="User profile" aria-expanded={profileOpen} aria-haspopup="true" onClick={() => setProfileOpen((value) => !value)}><span className="grid h-7 w-7 place-items-center rounded-md bg-raised text-[11px] font-semibold text-accent">{user?.name.slice(0, 2).toUpperCase()}</span><span className="hidden max-w-28 truncate text-xs font-medium sm:inline">{user?.name}</span><ChevronDown size={14} className="text-muted" aria-hidden="true" /></button>
              {profileOpen && <div className="absolute right-0 top-full z-50 mt-2 w-56 rounded-lg border border-line bg-surface p-1.5 shadow-xl"><div className="border-b border-line px-2.5 py-2"><p className="truncate text-xs font-semibold">{user?.name}</p><p className="truncate text-xs text-muted">{user?.email}</p></div><Link to="/settings" onClick={() => setProfileOpen(false)} className="mt-1 flex items-center gap-2 rounded-md px-2.5 py-2 text-sm text-foreground hover:bg-raised"><Settings2 size={15} />Settings</Link><button type="button" disabled={signingOut} onClick={() => void handleLogout()} className="flex w-full items-center gap-2 rounded-md px-2.5 py-2 text-left text-sm text-foreground hover:bg-raised"><LogOut size={15} />Sign out</button></div>}
            </div>
          </div>
        </header>
        {logoutError && <p role="alert" className="alert-error mx-4 mt-4 md:mx-6 lg:mx-8">{logoutError}</p>}
        <main ref={mainRef} id="main-content" tabIndex={-1} className="mx-auto w-full max-w-[1400px] px-4 pb-12 pt-6 outline-none md:px-6 lg:px-8 lg:pt-8"><div key={location.pathname} className="page-enter min-w-0">{children}</div></main>
      </div>
    </div>
  </div>
}
