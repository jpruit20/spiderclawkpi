/** SSE client and types for the AI dashboard editor. */

// ── types ──

export interface AiMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  toolCalls: AiToolEvent[]
  filesModified: string[]
  deploy?: { success: boolean; commit?: string | null; message?: string | null }
  isStreaming?: boolean
}

export interface AiToolEvent {
  tool: string
  file?: string | null
  kind: 'start' | 'use' | 'modified'
}

export type AiSSEEvent =
  | { type: 'text'; content: string }
  | { type: 'status'; message: string }
  | { type: 'tool_start'; tool: string; index: number }
  | { type: 'tool_use'; tool: string; file?: string | null }
  | { type: 'file_modified'; tool: string; file: string }
  | { type: 'deploy'; success: boolean; commit?: string | null; message?: string | null; reverted?: string[] | null }
  | { type: 'done'; result: string; files_changed: number; files: string[] }
  | { type: 'error'; message: string }

export interface AiAccessResponse {
  enabled: boolean
  divisions: string[]
}

// ── API base resolution (matches api.ts pattern) ──

function resolveApiBase(): string {
  const configured = (import.meta.env.VITE_API_BASE || '').trim().replace(/\/$/, '')
  if (typeof window !== 'undefined') {
    const { hostname, origin } = window.location
    if (hostname === 'kpi.spidergrills.com') return ''
    if (configured && configured === origin) return ''
  }
  return configured
}

const API_BASE = resolveApiBase()

// ── helpers ──

let _cachedAccess: AiAccessResponse | null = null

export async function fetchAiAccess(signal?: AbortSignal): Promise<AiAccessResponse> {
  if (_cachedAccess) return _cachedAccess
  const res = await fetch(`${API_BASE}/api/ai/access`, {
    credentials: 'include',
    signal,
  })
  if (!res.ok) return { enabled: false, divisions: [] }
  const data = await res.json()
  _cachedAccess = data
  return data
}

export function clearAiAccessCache() {
  _cachedAccess = null
}

// ── SSE streaming ──

export async function* streamAiMessage(
  division: string,
  message: string,
  history: { role: string; content: string }[],
  signal?: AbortSignal,
): AsyncGenerator<AiSSEEvent> {
  const res = await fetch(`${API_BASE}/api/ai/message`, {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ division, message, history }),
    signal,
  })

  if (!res.ok) {
    const text = await res.text().catch(() => 'Unknown error')
    yield { type: 'error', message: `Request failed (${res.status}): ${text}` }
    return
  }

  const reader = res.body?.getReader()
  if (!reader) {
    yield { type: 'error', message: 'No response stream' }
    return
  }

  const decoder = new TextDecoder()
  let buffer = ''

  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break

      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')
      buffer = lines.pop() || '' // keep the incomplete last line

      let currentEvent = ''
      for (const line of lines) {
        if (line.startsWith('event: ')) {
          currentEvent = line.slice(7).trim()
        } else if (line.startsWith('data: ') && currentEvent) {
          try {
            const data = JSON.parse(line.slice(6))
            yield { type: currentEvent, ...data } as AiSSEEvent
          } catch {
            // skip malformed JSON
          }
          currentEvent = ''
        } else if (line === '') {
          currentEvent = ''
        }
      }
    }
  } finally {
    reader.releaseLock()
  }
}
