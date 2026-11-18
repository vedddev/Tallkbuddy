import type { ReactNode } from 'react'

export function PageHeading({ eyebrow, title, description, action }: { eyebrow: string; title: string; description: string; action?: ReactNode }) {
  return <div className="mb-6 flex flex-col justify-between gap-4 sm:flex-row sm:items-end"><div className="min-w-0"><p className="eyebrow">{eyebrow}</p><h1 className="mt-1 text-2xl font-semibold tracking-tight text-foreground md:text-3xl">{title}</h1><p className="mt-2 max-w-2xl text-sm leading-6 text-muted">{description}</p></div>{action}</div>
}
