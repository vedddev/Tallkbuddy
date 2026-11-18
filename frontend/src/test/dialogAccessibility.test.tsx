import { useState } from 'react'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { Dialog } from '../components/ui/Primitives'

const originalShowModal = HTMLDialogElement.prototype.showModal
const originalClose = HTMLDialogElement.prototype.close

function ExampleDialog() {
  const [open, setOpen] = useState(false)
  return <><button onClick={() => setOpen(true)}>Open confirmation</button><Dialog open={open} title="Confirm action" onClose={() => setOpen(false)}>Review this action before continuing.</Dialog></>
}

beforeEach(() => {
  HTMLDialogElement.prototype.showModal = vi.fn(function (this: HTMLDialogElement) {
    this.setAttribute('open', '')
    this.querySelector('button')?.focus()
  })
  HTMLDialogElement.prototype.close = vi.fn(function (this: HTMLDialogElement) {
    this.removeAttribute('open')
  })
})
afterEach(() => {
  cleanup()
  HTMLDialogElement.prototype.showModal = originalShowModal
  HTMLDialogElement.prototype.close = originalClose
})

it('labels a modal, closes through Escape, and restores focus to its trigger', () => {
  render(<ExampleDialog />)
  const trigger = screen.getByRole('button', { name: 'Open confirmation' })
  trigger.focus()
  fireEvent.click(trigger)
  const dialog = screen.getByRole('dialog', { name: 'Confirm action' })
  expect(screen.getByRole('button', { name: 'Close dialog' })).toHaveFocus()
  fireEvent(dialog, new Event('cancel', { bubbles: true, cancelable: true }))
  expect(trigger).toHaveFocus()
  fireEvent.click(trigger)
  fireEvent.click(screen.getByRole('button', { name: 'Close dialog' }))
  expect(trigger).toHaveFocus()
})
