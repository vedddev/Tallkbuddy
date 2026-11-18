import { AudioLines } from 'lucide-react'
import { Link } from 'react-router-dom'

export function Logo({ compact = false, to = '/' }: { compact?: boolean; to?: string }) {
  return <Link to={to} className="inline-flex min-w-0 items-center gap-2.5 font-semibold tracking-tight text-foreground" aria-label="TalkBuddy home">
    <span className="grid h-9 w-9 shrink-0 place-items-center rounded-lg bg-accent text-[var(--color-primary-contrast)]"><AudioLines size={19} strokeWidth={2.2} /></span>
    {!compact && <span className="truncate text-lg">talk<span className="text-accent">buddy</span></span>}
  </Link>
}
