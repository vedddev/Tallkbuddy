import { fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ThemeProvider, useTheme } from '../contexts/ThemeContext'
import { Button, EmptyState, ErrorMessage, Input, Select, StatusIndicator, ToastRegion } from '../components/ui/Primitives'

afterEach(() => { localStorage.clear(); document.documentElement.classList.remove('dark') })

function ThemeControls() {
  const { theme, toggle } = useTheme()
  return <button onClick={toggle}>{theme}</button>
}

describe('design system', () => {
  it('starts dark, switches theme, and persists the choice', () => {
    render(<ThemeProvider><ThemeControls /></ThemeProvider>)
    expect(screen.getByRole('button', { name: 'dark' })).toBeInTheDocument()
    expect(document.documentElement).toHaveClass('dark')
    fireEvent.click(screen.getByRole('button', { name: 'dark' }))
    expect(screen.getByRole('button', { name: 'light' })).toBeInTheDocument()
    expect(document.documentElement).not.toHaveClass('dark')
    expect(localStorage.getItem('talkbuddy-theme')).toBe('light')
  })

  it('associates input errors and select help with controls', () => {
    render(<><Input id="email" label="Email" error="Enter a valid email" /><Select id="language" label="Language" hint="Choose a target"><option value="hi">Hindi</option></Select></>)
    expect(screen.getByLabelText('Email')).toHaveAttribute('aria-invalid', 'true')
    expect(screen.getByLabelText('Email')).toHaveAttribute('aria-describedby', 'email-help')
    expect(screen.getByLabelText('Language')).toHaveAttribute('aria-describedby', 'language-help')
  })

  it('renders loading, empty, status, and error information semantically', () => {
    render(<><Button busy>Save</Button><StatusIndicator label="Connected" tone="success" /><EmptyState title="No sessions" description="Saved sessions appear here." /><ErrorMessage message="Connection lost" /></>)
    expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled()
    expect(screen.getByRole('status', { name: 'Connected' })).toBeInTheDocument()
    expect(screen.getByText('No sessions')).toBeInTheDocument()
    expect(screen.getByRole('alert')).toHaveTextContent('Connection lost')
  })

  it('dismisses a toast by id', () => {
    const dismiss = vi.fn()
    render(<ToastRegion messages={[{ id: 'one', text: 'Saved' }]} onDismiss={dismiss} />)
    fireEvent.click(screen.getByRole('button', { name: 'Dismiss notification' }))
    expect(dismiss).toHaveBeenCalledWith('one')
  })
})
