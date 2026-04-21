import { useEffect, useState } from 'react'
import { api, type AIFeedbackArtifactType, type AIFeedbackReaction } from '../lib/api'

type Props = {
  artifactType: AIFeedbackArtifactType
  artifactId: string
  currentReaction?: AIFeedbackReaction | null
  compact?: boolean
  onChange?: (reaction: AIFeedbackReaction) => void
}

const PILLS: Array<{ key: AIFeedbackReaction; label: string; color: string; title: string }> = [
  { key: 'acted_on', label: 'Acted on', color: '#22c55e', title: 'This produced real action — we worked on it' },
  { key: 'already_knew', label: 'Already knew', color: '#f59e0b', title: 'True but not new information' },
  { key: 'wrong', label: 'Wrong', color: '#ef4444', title: 'False positive — this observation is not correct' },
  { key: 'ignore', label: 'Ignore', color: '#6b7280', title: 'Not relevant; skip it' },
]

export function FeedbackPills({ artifactType, artifactId, currentReaction, compact = false, onChange }: Props) {
  const [active, setActive] = useState<AIFeedbackReaction | null>(currentReaction ?? null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  useEffect(() => { setActive(currentReaction ?? null) }, [currentReaction])

  const pick = async (r: AIFeedbackReaction) => {
    if (busy) return
    const prev = active
    setActive(r)
    setBusy(true)
    setErr(null)
    try {
      await api.aiFeedbackPost({ artifact_type: artifactType, artifact_id: artifactId, reaction: r })
      onChange?.(r)
    } catch (e: unknown) {
      setActive(prev)
      setErr(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  const fontSize = compact ? 10 : 11
  const pad = compact ? '2px 6px' : '3px 8px'

  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 4, flexWrap: 'wrap' }}>
      {PILLS.map(p => {
        const on = active === p.key
        return (
          <button
            key={p.key}
            type="button"
            title={p.title}
            onClick={(e) => { e.stopPropagation(); pick(p.key) }}
            disabled={busy}
            style={{
              fontSize,
              padding: pad,
              border: `1px solid ${on ? p.color : 'var(--border)'}`,
              background: on ? p.color : 'transparent',
              color: on ? '#fff' : 'var(--muted)',
              borderRadius: 999,
              cursor: busy ? 'wait' : 'pointer',
              lineHeight: 1.2,
              opacity: busy && !on ? 0.5 : 1,
            }}
          >
            {p.label}
          </button>
        )
      })}
      {err ? <span style={{ fontSize: 10, color: 'var(--red)' }}>{err}</span> : null}
    </div>
  )
}

export function useMyFeedback(artifactType: AIFeedbackArtifactType) {
  const [map, setMap] = useState<Map<string, AIFeedbackReaction>>(new Map())
  useEffect(() => {
    let alive = true
    api.aiFeedbackMine(artifactType).then(r => {
      if (!alive) return
      const m = new Map<string, AIFeedbackReaction>()
      for (const x of r.reactions) m.set(x.artifact_id, x.reaction)
      setMap(m)
    }).catch(() => {})
    return () => { alive = false }
  }, [artifactType])
  const update = (artifactId: string, reaction: AIFeedbackReaction) => {
    setMap(prev => {
      const next = new Map(prev)
      next.set(artifactId, reaction)
      return next
    })
  }
  return { reactions: map, updateReaction: update }
}
