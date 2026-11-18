import { useEffect, useId, useRef, type ButtonHTMLAttributes, type HTMLAttributes, type InputHTMLAttributes, type ReactNode, type SelectHTMLAttributes } from 'react'
import { AlertCircle, Inbox, LoaderCircle, X } from 'lucide-react'

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & { variant?: 'primary' | 'secondary' | 'ghost'; busy?: boolean }

export function Button({ variant = 'secondary', busy = false, children, disabled, className = '', ...props }: ButtonProps) {
  const style = variant === 'primary' ? 'btn-primary' : variant === 'ghost' ? 'icon-btn' : 'btn-secondary'
  return <button {...props} disabled={disabled || busy} aria-busy={busy || undefined} className={`${style} ${className}`}>
    {busy && <LoaderCircle size={16} className="animate-spin" aria-hidden="true" />}{children}
  </button>
}

type FieldProps = InputHTMLAttributes<HTMLInputElement> & { label: string; hint?: string; error?: string }

export function Input({ label, hint, error, id, className = '', ...props }: FieldProps) {
  const fieldId = id || label.toLowerCase().replace(/\W+/g, '-')
  const helpId = `${fieldId}-help`
  return <div className="grid gap-1.5"><label htmlFor={fieldId} className="text-sm font-medium">{label}</label>
    <input {...props} id={fieldId} aria-invalid={Boolean(error)} aria-describedby={hint || error ? helpId : undefined} className={`field w-full ${className}`} />
    {(error || hint) && <p id={helpId} className="text-xs" style={{ color: error ? 'var(--color-danger)' : 'var(--color-muted)' }}>{error || hint}</p>}
  </div>
}

type SelectProps = SelectHTMLAttributes<HTMLSelectElement> & { label: string; hint?: string; error?: string; children: ReactNode }

export function Select({ label, hint, error, id, className = '', children, ...props }: SelectProps) {
  const fieldId = id || label.toLowerCase().replace(/\W+/g, '-')
  const helpId = `${fieldId}-help`
  return <div className="grid gap-1.5"><label htmlFor={fieldId} className="text-sm font-medium">{label}</label>
    <select {...props} id={fieldId} aria-invalid={Boolean(error)} aria-describedby={hint || error ? helpId : undefined} className={`field w-full ${className}`}>{children}</select>
    {(error || hint) && <p id={helpId} className="text-xs" style={{ color: error ? 'var(--color-danger)' : 'var(--color-muted)' }}>{error || hint}</p>}
  </div>
}

export function Card({ children, className = '', ...props }: HTMLAttributes<HTMLElement>) {
  return <section {...props} className={`panel ${className}`}>{children}</section>
}

export function StatusIndicator({ label, tone = 'neutral' }: { label: string; tone?: 'neutral' | 'success' | 'warning' | 'danger' }) {
  const color = tone === 'success' ? 'var(--color-success)' : tone === 'warning' ? 'var(--color-warning)' : tone === 'danger' ? 'var(--color-danger)' : 'var(--color-muted)'
  return <span role="status" aria-label={label} className="inline-flex items-center gap-2 text-xs font-medium" style={{ color }}><span className="h-1.5 w-1.5 rounded-full bg-current" aria-hidden="true" />{label}</span>
}

export function Tooltip({ text, children }: { text: string; children: ReactNode }) {
  return <span className="group relative inline-flex" title={text}>{children}<span aria-hidden="true" className="ui-tooltip">{text}</span></span>
}

export function Dialog({ open, title, onClose, children, actions }: { open: boolean; title: string; onClose: () => void; children: ReactNode; actions?: ReactNode }) {
  const ref = useRef<HTMLDialogElement>(null)
  const titleId = useId()
  useEffect(() => {
    const node = ref.current
    if (!node) return
    if (open && !node.open) {
      const previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null
      node.showModal()
      return () => {
        if (node.open) node.close()
        previousFocus?.focus()
      }
    }
    if (!open && node.open) node.close()
  }, [open])
  return <dialog ref={ref} onClose={onClose} onCancel={(event) => { event.preventDefault(); onClose() }} aria-labelledby={titleId} className="dialog-enter w-[min(92vw,480px)] rounded-xl border border-line bg-surface p-0 text-foreground shadow-2xl backdrop:bg-black/65">
    <div className="flex items-center justify-between border-b border-line px-5 py-4"><h2 id={titleId} className="text-base font-semibold">{title}</h2><Button variant="ghost" aria-label="Close dialog" onClick={onClose}><X size={17} /></Button></div>
    <div className="p-5 text-sm text-muted">{children}</div>{actions && <div className="flex justify-end gap-2 border-t border-line px-5 py-4">{actions}</div>}
  </dialog>
}

export type ToastMessage = { id: string; text: string; tone?: 'success' | 'warning' | 'danger' }

export function ToastRegion({ messages, onDismiss }: { messages: ToastMessage[]; onDismiss: (id: string) => void }) {
  return <div aria-live="polite" className="pointer-events-none fixed bottom-4 right-4 z-50 flex w-[min(92vw,360px)] flex-col gap-2">
    {messages.map((message) => <div key={message.id} role={message.tone === 'danger' ? 'alert' : 'status'} className="pointer-events-auto flex items-start justify-between gap-3 rounded-lg border border-line bg-surface p-3 text-sm text-foreground shadow-lg"><span>{message.text}</span><button className="icon-btn -m-1" type="button" onClick={() => onDismiss(message.id)} aria-label="Dismiss notification"><X size={15} /></button></div>)}
  </div>
}

export function LoadingState({ label = 'Loading…' }: { label?: string }) {
  return <div role="status" className="flex items-center justify-center gap-2 p-8 text-sm text-muted"><LoaderCircle size={17} className="animate-spin" aria-hidden="true" />{label}</div>
}

export function EmptyState({ title, description, action }: { title: string; description: string; action?: ReactNode }) {
  return <div className="flex flex-col items-center gap-2 p-10 text-center"><Inbox size={24} className="text-muted" aria-hidden="true" /><h3 className="mt-2 text-sm font-semibold">{title}</h3><p className="max-w-sm text-sm text-muted">{description}</p>{action && <div className="mt-3">{action}</div>}</div>
}

export function ErrorMessage({ message }: { message: string }) {
  return <p role="alert" className="alert-error flex items-start gap-2"><AlertCircle size={17} className="shrink-0" aria-hidden="true" />{message}</p>
}
