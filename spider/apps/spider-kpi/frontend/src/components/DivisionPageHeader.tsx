import { useState } from 'react'
import type { UsePageConfigResult } from '../lib/usePageConfig'

/**
 * Toolbar that division leads see at the top of their page. Shows:
 *   - Permission state (you can edit / read-only)
 *   - Customize mode toggle (when permitted)
 *   - Save / Reset / Audit-log buttons (when in customize mode)
 *   - Pending-changes badge
 *
 * The page-config hook provides everything; this is just the chrome.
 */
interface Props {
  cfg: ReturnType<typeof import('../lib/usePageConfig').usePageConfig>
  divisionLabel: string
}

export function DivisionPageHeader({ cfg, divisionLabel }: Props) {
  const [savingMsg, setSavingMsg] = useState<string | null>(null)
  const [showAudit, setShowAudit] = useState(false)
  const audit = cfg.config?.audit_log ?? []

  async function doSave() {
    try {
      setSavingMsg('Saving…')
      await cfg.save(`Customize mode update at ${new Date().toLocaleTimeString()}`)
      setSavingMsg('✓ Saved')
      setTimeout(() => setSavingMsg(null), 1500)
    } catch (err) {
      setSavingMsg('✗ ' + (err instanceof Error ? err.message : 'Save failed'))
      setTimeout(() => setSavingMsg(null), 4000)
    }
  }

  async function doReset() {
    if (!confirm('Reset this page to defaults? Your custom card order, hidden cards, and titles will be cleared.')) return
    try {
      setSavingMsg('Resetting…')
      await cfg.reset()
      cfg.setCustomizeMode(false)
      setSavingMsg('✓ Reset')
      setTimeout(() => setSavingMsg(null), 1500)
    } catch (err) {
      setSavingMsg('✗ ' + (err instanceof Error ? err.message : 'Reset failed'))
    }
  }

  return (
    <div
      style={{
        display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap',
        padding: '6px 10px', background: 'var(--panel-2)', borderRadius: 4,
        marginBottom: 4,
        borderLeft: cfg.customizeMode ? '3px solid var(--orange)' : '3px solid var(--blue)',
      }}
    >
      <strong style={{ fontSize: 12 }}>{divisionLabel}</strong>
      <span style={{ fontSize: 10, color: 'var(--muted)' }}>
        {cfg.canEdit ? `· you have edit access` : `· read-only`}
      </span>
      {cfg.dirty && (
        <span style={{ fontSize: 10, color: 'var(--orange)', fontWeight: 600 }}>
          · unsaved changes
        </span>
      )}
      <span style={{ flex: 1 }} />
      {cfg.canEdit && !cfg.customizeMode && (
        <button
          onClick={() => cfg.setCustomizeMode(true)}
          style={{ background: 'var(--panel)', border: '1px solid rgba(255,255,255,0.1)', color: 'var(--text)', padding: '3px 9px', borderRadius: 3, fontSize: 11, fontWeight: 600, cursor: 'pointer' }}
          title="Customize: reorder, hide, rename cards on this page"
        >
          🎛 Customize
        </button>
      )}
      {cfg.customizeMode && (
        <>
          <button
            onClick={doSave}
            disabled={!cfg.dirty}
            style={{
              background: cfg.dirty ? 'var(--green)' : 'var(--panel)',
              border: '1px solid rgba(255,255,255,0.1)',
              color: cfg.dirty ? '#fff' : 'var(--muted)',
              padding: '3px 9px', borderRadius: 3, fontSize: 11, fontWeight: 600,
              cursor: cfg.dirty ? 'pointer' : 'not-allowed',
            }}
          >
            💾 Save
          </button>
          <button
            onClick={doReset}
            style={{ background: 'var(--panel)', border: '1px solid rgba(255,255,255,0.1)', color: 'var(--red)', padding: '3px 9px', borderRadius: 3, fontSize: 11, cursor: 'pointer' }}
          >
            ↻ Reset
          </button>
          <button
            onClick={() => setShowAudit(s => !s)}
            style={{ background: 'var(--panel)', border: '1px solid rgba(255,255,255,0.1)', color: 'var(--muted)', padding: '3px 9px', borderRadius: 3, fontSize: 11, cursor: 'pointer' }}
          >
            📜 Audit ({audit.length})
          </button>
          <button
            onClick={() => cfg.setCustomizeMode(false)}
            style={{ background: 'var(--panel)', border: '1px solid rgba(255,255,255,0.1)', color: 'var(--muted)', padding: '3px 9px', borderRadius: 3, fontSize: 11, cursor: 'pointer' }}
          >
            ✕ Done
          </button>
        </>
      )}
      {savingMsg && (
        <span style={{ fontSize: 11, color: savingMsg.startsWith('✓') ? 'var(--green)' : savingMsg.startsWith('✗') ? 'var(--red)' : 'var(--muted)' }}>
          {savingMsg}
        </span>
      )}
      {cfg.customizeMode && showAudit && audit.length > 0 && (
        <div style={{ width: '100%', marginTop: 6, fontSize: 10, color: 'var(--muted)' }}>
          <strong style={{ display: 'block', marginBottom: 3, color: 'var(--text)' }}>Recent changes</strong>
          {audit.slice(-10).reverse().map((a, i) => (
            <div key={i} style={{ paddingLeft: 8, fontVariantNumeric: 'tabular-nums' }}>
              <code style={{ marginRight: 6 }}>{a.at?.slice(0, 19).replace('T', ' ')}</code>
              <span style={{ color: 'var(--blue)' }}>{a.by?.split('@')[0]}</span>
              <span style={{ marginLeft: 6 }}>{a.change_summary}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
