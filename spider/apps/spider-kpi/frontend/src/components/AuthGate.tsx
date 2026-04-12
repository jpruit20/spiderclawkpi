import { FormEvent, createContext, useContext, useEffect, useMemo, useState } from 'react'

import type { AuthStatusResponse, AuthUserSummary } from '../lib/types'
import { ApiError, api } from '../lib/api'

type AuthStep = 'email' | 'code'

type AuthContextValue = {
  user: AuthUserSummary | null
  authDisabled: boolean
  refreshStatus: () => Promise<void>
  logout: () => Promise<void>
}

const AuthContext = createContext<AuthContextValue | null>(null)

function formatAuthError(err: unknown, fallback: string) {
  const message = err instanceof ApiError ? err.message : fallback
  return message
    .replace(/^API error \d+ for \/api\/auth\/(request-code|verify-code|login|signup|logout): ?/, '')
    .replace(/^\{"detail":"/i, '')
    .replace(/"\}$/i, '')
}

export function useAuth() {
  const value = useContext(AuthContext)
  if (!value) {
    throw new Error('useAuth must be used inside AuthGate')
  }
  return value
}

export function AuthGate({ children }: { children: React.ReactNode }) {
  const [loading, setLoading] = useState(true)
  const [status, setStatus] = useState<AuthStatusResponse>({ authenticated: false, auth_disabled: false, allowed_domains: [], user: null })
  const [step, setStep] = useState<AuthStep>('email')
  const [email, setEmail] = useState('')
  const [code, setCode] = useState('')
  const [message, setMessage] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  async function refreshStatus() {
    const nextStatus = await api.authStatus()
    setStatus(nextStatus)
  }

  useEffect(() => {
    let active = true
    api.authStatus()
      .then((nextStatus) => {
        if (!active) return
        setStatus(nextStatus)
      })
      .catch(() => {
        if (!active) return
        setStatus({ authenticated: false, auth_disabled: false, allowed_domains: [], user: null })
      })
      .finally(() => {
        if (!active) return
        setLoading(false)
      })
    return () => {
      active = false
    }
  }, [])

  async function logout() {
    setSubmitting(true)
    setError(null)
    setMessage(null)
    try {
      await api.logout()
      await refreshStatus()
      setStep('email')
      setCode('')
    } catch (err) {
      setError(formatAuthError(err, 'Unable to sign out right now'))
    } finally {
      setSubmitting(false)
    }
  }

  async function handleRequestCode(event: FormEvent) {
    event.preventDefault()
    setSubmitting(true)
    setError(null)
    setMessage(null)

    try {
      const response = await api.requestVerificationCode(email)
      setMessage(response.detail)
      setStep('code')
    } catch (err) {
      setError(formatAuthError(err, 'Unable to send verification code'))
    } finally {
      setSubmitting(false)
    }
  }

  async function handleVerifyCode(event: FormEvent) {
    event.preventDefault()
    setSubmitting(true)
    setError(null)
    setMessage(null)

    try {
      const nextStatus = await api.verifyVerificationCode(email, code)
      setStatus(nextStatus)
      setCode('')
    } catch (err) {
      setError(formatAuthError(err, 'Unable to verify code'))
    } finally {
      setSubmitting(false)
    }
  }

  const contextValue = useMemo<AuthContextValue>(() => ({
    user: status.user ?? null,
    authDisabled: Boolean(status.auth_disabled),
    refreshStatus,
    logout,
  }), [status.user, status.auth_disabled])

  if (loading) {
    return (
      <div className="auth-shell">
        <div className="auth-card">
          <h1>Loading dashboard</h1>
          <p>Checking access…</p>
        </div>
      </div>
    )
  }

  if (status.authenticated) {
    return <AuthContext.Provider value={contextValue}>{children}</AuthContext.Provider>
  }

  return (
    <div className="auth-shell">
      <form className="auth-card" onSubmit={step === 'email' ? handleRequestCode : handleVerifyCode}>
        <div className="auth-eyebrow">Dashboard access</div>
        <h1>{step === 'email' ? 'Request access code' : 'Enter verification code'}</h1>
        <p>
          {step === 'email'
            ? 'Enter your work email and, if it is eligible, we will send a 6-digit access code.'
            : 'Check your email for the 6-digit code, then enter it below to continue.'}
        </p>

        <label className="auth-label" htmlFor="dashboard-email">Work email</label>
        <input
          id="dashboard-email"
          className="auth-input"
          type="email"
          value={email}
          onChange={(event) => setEmail(event.target.value)}
          autoComplete="email"
          placeholder="you@company.com"
          required
          disabled={submitting || step === 'code'}
        />

        {step === 'code' ? (
          <>
            <label className="auth-label" htmlFor="dashboard-code">Verification code</label>
            <input
              id="dashboard-code"
              className="auth-input"
              type="text"
              inputMode="numeric"
              pattern="[0-9]{6}"
              maxLength={6}
              value={code}
              onChange={(event) => setCode(event.target.value.replace(/\D/g, '').slice(0, 6))}
              autoComplete="one-time-code"
              placeholder="123456"
              required
            />
            <div className="auth-hint">Codes expire after 15 minutes.</div>
          </>
        ) : null}

        {message ? <div className="auth-hint">{message}</div> : null}
        {error ? <div className="auth-error">{error}</div> : null}

        <button className="auth-button" type="submit" disabled={submitting || !email.trim() || (step === 'code' && code.trim().length !== 6)}>
          {submitting
            ? (step === 'email' ? 'Sending code…' : 'Verifying…')
            : (step === 'email' ? 'Send code' : 'Verify and continue')}
        </button>

        {step === 'code' ? (
          <div className="auth-toggle-row">
            <button
              type="button"
              className="auth-toggle"
              onClick={() => {
                setStep('email')
                setCode('')
                setError(null)
                setMessage(null)
              }}
            >
              Use a different email
            </button>
            <button
              type="button"
              className="auth-toggle"
              onClick={async () => {
                setSubmitting(true)
                setError(null)
                setMessage(null)
                try {
                  const response = await api.requestVerificationCode(email)
                  setMessage(response.detail)
                } catch (err) {
                  setError(formatAuthError(err, 'Unable to resend verification code'))
                } finally {
                  setSubmitting(false)
                }
              }}
              disabled={submitting}
            >
              Resend code
            </button>
          </div>
        ) : null}
      </form>
    </div>
  )
}
