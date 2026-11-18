import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { AuthPage } from '../pages/AuthPage'
import { ThemeProvider } from '../contexts/ThemeContext'

const { login, register } = vi.hoisted(() => ({ login: vi.fn(), register: vi.fn() }))
vi.mock('../contexts/AuthContext', () => ({
  useAuth: () => ({ user: null, login, register }),
}))

function renderAuth(path: '/login' | '/register') {
  return render(<ThemeProvider><MemoryRouter initialEntries={[path]}><Routes>
    <Route path="/login" element={<AuthPage mode="login" />} />
    <Route path="/register" element={<AuthPage mode="register" />} />
  </Routes></MemoryRouter></ThemeProvider>)
}

beforeEach(() => { login.mockReset(); register.mockReset(); localStorage.clear() })
afterEach(() => { cleanup(); document.documentElement.classList.remove('dark') })

describe('authentication pages', () => {
  it('labels fields, reveals the password with a keyboard-operable button, and changes theme', () => {
    renderAuth('/login')
    const password = screen.getByLabelText('Password')
    expect(password).toHaveAttribute('type', 'password')
    const reveal = screen.getByRole('button', { name: 'Show password' })
    reveal.focus()
    fireEvent.click(reveal)
    expect(password).toHaveAttribute('type', 'text')
    expect(screen.getByRole('button', { name: 'Hide password' })).toHaveAttribute('aria-pressed', 'true')
    fireEvent.click(screen.getByRole('button', { name: 'Use light theme' }))
    expect(localStorage.getItem('talkbuddy-theme')).toBe('light')
    expect(document.documentElement).not.toHaveClass('dark')
  })

  it('requires valid registration fields and prevents duplicate submission while loading', async () => {
    let finish!: () => void
    register.mockImplementation(() => new Promise<void>((resolve) => { finish = resolve }))
    renderAuth('/register')
    const submit = screen.getByRole('button', { name: 'Create account' })
    const form = submit.closest('form')!
    expect(form.checkValidity()).toBe(false)
    fireEvent.change(screen.getByLabelText('Your name'), { target: { value: 'Taylor' } })
    fireEvent.change(screen.getByLabelText('Email address'), { target: { value: 'taylor@example.com' } })
    fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'twelve-character-password' } })
    expect(form.checkValidity()).toBe(true)
    fireEvent.click(submit)
    expect(await screen.findByRole('button', { name: 'Please wait...' })).toBeDisabled()
    expect(register).toHaveBeenCalledTimes(1)
    finish()
    expect(await screen.findByRole('status')).toHaveTextContent('Account created')
    expect(screen.getByLabelText('Password')).toHaveAttribute('type', 'password')
  })

  it('shows a helpful login error without navigating away', async () => {
    login.mockRejectedValue(new Error('Incorrect email or password.'))
    renderAuth('/login')
    fireEvent.change(screen.getByLabelText('Email address'), { target: { value: 'taylor@example.com' } })
    fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'wrong-password' } })
    fireEvent.click(screen.getByRole('button', { name: 'Sign in' }))
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('Incorrect email or password.'))
    expect(screen.getByRole('heading', { name: 'Good to have you back.' })).toBeInTheDocument()
  })
})
