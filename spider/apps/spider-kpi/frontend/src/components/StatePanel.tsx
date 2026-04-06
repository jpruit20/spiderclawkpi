import { ReactNode } from 'react'

export type StateTone = 'good' | 'warn' | 'bad' | 'muted' | 'neutral'
export type StateKind = 'loading' | 'empty' | 'error' | 'partial' | 'ready'

function titleFor(kind: StateKind, fallback?: string) {
  if (fallback) return fallback
  switch (kind) {
    case 'loading':
      return 'Loading'
    case 'empty':
      return 'No data available'
    case 'error':
      return 'Data unavailable'
    case 'partial':
      return 'Partial coverage'
    case 'ready':
    default:
      return 'Ready'
  }
}

export function StatePanel({
  kind,
  tone = 'neutral',
  title,
  message,
  detail,
  action,
}: {
  kind: StateKind
  tone?: StateTone
  title?: string
  message: string
  detail?: ReactNode
  action?: ReactNode
}) {
  return (
    <div className={`state-panel status-${tone}`} data-kind={kind}>
      <div>
        <strong>{titleFor(kind, title)}</strong>
        <p>{message}</p>
        {detail ? <small>{detail}</small> : null}
      </div>
      {action ? <div className="state-panel-action">{action}</div> : null}
    </div>
  )
}
