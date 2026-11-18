import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import { AppShell } from '../components/AppShell'
import { ThemeProvider } from '../contexts/ThemeContext'

const { logout } = vi.hoisted(() => ({ logout: vi.fn().mockResolvedValue(undefined) }))
vi.mock('../contexts/AuthContext', () => ({
  useAuth: () => ({ user: { name: 'Taylor', email: 'taylor@example.com' }, logout }),
}))

function renderShell(path = '/overview') {
  return render(<ThemeProvider><MemoryRouter initialEntries={[path]}><AppShell><h1>Current content</h1><section id="meeting">Meeting section</section><section id="translate">Translation section</section></AppShell></MemoryRouter></ThemeProvider>)
}

beforeEach(() => { localStorage.clear(); logout.mockClear(); window.history.pushState({}, '', '/') })
afterEach(() => { cleanup(); document.documentElement.classList.remove('dark'); document.body.style.overflow = '' })

describe('application shell', () => {
  it('links to existing workspace sections and highlights the active location', () => {
    renderShell()
    const nav = screen.getByRole('navigation', { name: 'Primary navigation' })
    expect(nav.querySelectorAll('a')).toHaveLength(5)
    expect(screen.getByRole('link', { name: 'Overview' })).toHaveAttribute('aria-current', 'page')
    expect(screen.getByRole('link', { name: 'Translate' })).toHaveAttribute('href', '/translate')
    expect(screen.getByRole('link', { name: 'Live Meeting' })).toHaveAttribute('href', '/meeting')
    fireEvent.click(screen.getByRole('link', { name: 'Live Meeting' }))
    expect(screen.getByRole('link', { name: 'Live Meeting' })).toHaveAttribute('aria-current', 'page')
    expect(screen.getByText('Live Meeting', { selector: 'header span' })).toBeInTheDocument()
  })

  it('collapses the desktop sidebar and persists that preference', () => {
    renderShell()
    fireEvent.click(screen.getByRole('button', { name: 'Collapse sidebar' }))
    expect(screen.getByRole('button', { name: 'Expand sidebar' })).toHaveAttribute('aria-expanded', 'false')
    expect(localStorage.getItem('talkbuddy-sidebar-collapsed')).toBe('true')
  })

  it('opens the mobile drawer, closes it on navigation and Escape, and restores focus', () => {
    Object.defineProperty(window, 'innerWidth', { configurable: true, value: 390 })
    renderShell()
    const trigger = screen.getByRole('button', { name: 'Open navigation' })
    fireEvent.click(trigger)
    expect(screen.getByRole('dialog', { name: 'Navigation drawer' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Close navigation' })).toHaveFocus()
    screen.getByRole('link', { name: 'TalkBuddy home' }).focus()
    fireEvent.keyDown(screen.getByRole('dialog', { name: 'Navigation drawer' }), { key: 'Tab', shiftKey: true })
    expect(screen.getByRole('link', { name: 'Settings' })).toHaveFocus()
    fireEvent.keyDown(screen.getByRole('dialog', { name: 'Navigation drawer' }), { key: 'Tab' })
    expect(screen.getByRole('link', { name: 'TalkBuddy home' })).toHaveFocus()
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(screen.queryByRole('dialog', { name: 'Navigation drawer' })).not.toBeInTheDocument()
    expect(trigger).toHaveFocus()
    fireEvent.click(trigger)
    fireEvent.click(screen.getByRole('link', { name: 'Translate' }))
    expect(screen.queryByRole('dialog', { name: 'Navigation drawer' })).not.toBeInTheDocument()
    expect(document.getElementById('main-content')).toHaveFocus()
    Object.defineProperty(window, 'innerWidth', { configurable: true, value: 1024 })
  })

  it('toggles theme and signs out through the profile menu', async () => {
    renderShell()
    fireEvent.click(screen.getByRole('button', { name: 'Use light theme' }))
    expect(localStorage.getItem('talkbuddy-theme')).toBe('light')
    fireEvent.click(screen.getByRole('button', { name: 'User profile' }))
    expect(screen.getByText('taylor@example.com', { selector: 'div.absolute p' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Sign out' }))
    await waitFor(() => expect(logout).toHaveBeenCalledTimes(1))
  })
})
