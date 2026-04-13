import { useCallback, useEffect, useRef, useState } from 'react'
import { useAuth } from './AuthGate'
import type { AiMessage, AiToolEvent, AiSSEEvent } from '../lib/aiChat'
import { streamAiMessage } from '../lib/aiChat'

let _nextId = 1
function uid() {
  return `msg-${_nextId++}-${Date.now()}`
}

const DIVISION_LABELS: Record<string, string> = {
  marketing: 'Marketing',
  'customer-experience': 'Customer Experience',
  'product-engineering': 'Product / Engineering',
  operations: 'Operations',
  'production-manufacturing': 'Production / Manufacturing',
}

export function ChatPanel({ division }: { division: string }) {
  const { user } = useAuth()
  const [open, setOpen] = useState(false)
  const [messages, setMessages] = useState<AiMessage[]>([])
  const [input, setInput] = useState('')
  const [streaming, setStreaming] = useState(false)
  const abortRef = useRef<AbortController | null>(null)
  const scrollRef = useRef<HTMLDivElement>(null)

  // Only show if user has AI access for this division
  const hasAccess = user?.ai_divisions?.includes(division)
  if (!hasAccess) return null

  const label = DIVISION_LABELS[division] || division

  const scrollToBottom = useCallback(() => {
    requestAnimationFrame(() => {
      scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' })
    })
  }, [])

  useEffect(scrollToBottom, [messages, scrollToBottom])

  const handleSend = useCallback(async () => {
    const text = input.trim()
    if (!text || streaming) return

    const userMsg: AiMessage = {
      id: uid(),
      role: 'user',
      content: text,
      toolCalls: [],
      filesModified: [],
    }

    const assistantMsg: AiMessage = {
      id: uid(),
      role: 'assistant',
      content: '',
      toolCalls: [],
      filesModified: [],
      isStreaming: true,
    }

    setMessages(prev => [...prev, userMsg, assistantMsg])
    setInput('')
    setStreaming(true)

    const history = messages
      .filter(m => m.role === 'user' || (m.role === 'assistant' && m.content))
      .slice(-10)
      .map(m => ({ role: m.role, content: m.content }))

    const controller = new AbortController()
    abortRef.current = controller

    try {
      for await (const evt of streamAiMessage(division, text, history, controller.signal)) {
        setMessages(prev => {
          const updated = [...prev]
          const last = { ...updated[updated.length - 1] }

          switch (evt.type) {
            case 'text':
              last.content += (evt as Extract<AiSSEEvent, { type: 'text' }>).content
              break
            case 'status':
              // Status events update content as a note
              break
            case 'tool_start': {
              const e = evt as Extract<AiSSEEvent, { type: 'tool_start' }>
              last.toolCalls = [...last.toolCalls, { tool: e.tool, kind: 'start' }]
              break
            }
            case 'tool_use': {
              const e = evt as Extract<AiSSEEvent, { type: 'tool_use' }>
              last.toolCalls = [...last.toolCalls, { tool: e.tool, file: e.file, kind: 'use' }]
              break
            }
            case 'file_modified': {
              const e = evt as Extract<AiSSEEvent, { type: 'file_modified' }>
              last.filesModified = [...last.filesModified, e.file]
              last.toolCalls = [...last.toolCalls, { tool: e.tool, file: e.file, kind: 'modified' }]
              break
            }
            case 'deploy': {
              const e = evt as Extract<AiSSEEvent, { type: 'deploy' }>
              last.deploy = { success: e.success, commit: e.commit, message: e.message }
              break
            }
            case 'done':
              last.isStreaming = false
              break
            case 'error': {
              const e = evt as Extract<AiSSEEvent, { type: 'error' }>
              last.content += `\n\n**Error:** ${e.message}`
              last.isStreaming = false
              break
            }
          }

          updated[updated.length - 1] = last
          return updated
        })
      }
    } catch (err: unknown) {
      if (err instanceof DOMException && err.name === 'AbortError') return
      setMessages(prev => {
        const updated = [...prev]
        const last = { ...updated[updated.length - 1] }
        last.content += `\n\n**Error:** ${err instanceof Error ? err.message : 'Unknown error'}`
        last.isStreaming = false
        updated[updated.length - 1] = last
        return updated
      })
    } finally {
      setStreaming(false)
      abortRef.current = null
      // Mark streaming done on last message
      setMessages(prev => {
        const updated = [...prev]
        const last = { ...updated[updated.length - 1] }
        last.isStreaming = false
        updated[updated.length - 1] = last
        return updated
      })
    }
  }, [input, streaming, messages, division])

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault()
        handleSend()
      }
    },
    [handleSend],
  )

  const handleStop = useCallback(() => {
    abortRef.current?.abort()
  }, [])

  // ── collapsed toggle ──
  if (!open) {
    return (
      <button className="chat-toggle" onClick={() => setOpen(true)} title="AI Assistant">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
        </svg>
        <span>AI Assistant</span>
      </button>
    )
  }

  // ── expanded panel ──
  return (
    <div className="chat-panel open">
      <div className="chat-header">
        <div className="chat-header-title">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
          </svg>
          <span>AI Assistant — {label}</span>
        </div>
        <button className="chat-close" onClick={() => setOpen(false)} title="Close">
          &times;
        </button>
      </div>

      <div className="chat-messages" ref={scrollRef}>
        {messages.length === 0 && (
          <div className="chat-empty">
            Ask me to make changes to your {label} dashboard page. For example:
            <ul>
              <li>"Add a new KPI card for return rate"</li>
              <li>"Change the chart to show a 30-day trend"</li>
              <li>"Move the action items section above the charts"</li>
            </ul>
          </div>
        )}
        {messages.map(msg => (
          <div key={msg.id} className={`chat-msg chat-msg-${msg.role}`}>
            <div className="chat-msg-role">{msg.role === 'user' ? 'You' : 'AI'}</div>
            <div className="chat-msg-content">
              {msg.content && <div className="chat-msg-text">{msg.content}</div>}
              {msg.toolCalls.length > 0 && (
                <div className="chat-msg-tools">
                  {msg.toolCalls.map((tc, i) => (
                    <ToolCallBadge key={i} tc={tc} />
                  ))}
                </div>
              )}
              {msg.filesModified.length > 0 && (
                <div className="chat-msg-files">
                  {msg.filesModified.map((f, i) => (
                    <span key={i} className="chat-file-badge">Modified: {f.split('/').pop()}</span>
                  ))}
                </div>
              )}
              {msg.deploy && (
                <div className={`chat-deploy ${msg.deploy.success ? 'chat-deploy-ok' : 'chat-deploy-fail'}`}>
                  {msg.deploy.success
                    ? `Deployed (${msg.deploy.commit})`
                    : `Deploy issue: ${msg.deploy.message}`}
                </div>
              )}
              {msg.isStreaming && <span className="chat-cursor" />}
            </div>
          </div>
        ))}
      </div>

      <div className="chat-input-area">
        <textarea
          className="chat-input"
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={`Describe a change to the ${label} page...`}
          rows={2}
          disabled={streaming}
        />
        <div className="chat-input-actions">
          {streaming ? (
            <button className="chat-btn chat-btn-stop" onClick={handleStop}>
              Stop
            </button>
          ) : (
            <button
              className="chat-btn chat-btn-send"
              onClick={handleSend}
              disabled={!input.trim()}
            >
              Send
            </button>
          )}
        </div>
      </div>
    </div>
  )
}

function ToolCallBadge({ tc }: { tc: AiToolEvent }) {
  const icon = tc.kind === 'modified' ? 'pencil' : tc.kind === 'start' ? 'dots' : 'eye'
  const label =
    tc.kind === 'modified'
      ? `Edited ${tc.file?.split('/').pop() || 'file'}`
      : tc.kind === 'start'
        ? `${tc.tool}...`
        : `${tc.tool} ${tc.file?.split('/').pop() || ''}`
  return (
    <span className={`chat-tool-badge chat-tool-${icon}`}>
      {label}
    </span>
  )
}
