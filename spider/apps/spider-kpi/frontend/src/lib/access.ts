/**
 * Client-side role + page-scope helpers.
 *
 * Mirrors backend/app/services/access_control.py. These helpers are UI
 * affordances (hide nav items, redirect out-of-scope routes, hide edit
 * buttons). They are not the security boundary — the backend's
 * `require_editor` guard enforces write-access server-side.
 */
import type { AuthUserSummary } from './types'

export type Role = 'admin' | 'editor' | 'viewer'

export function userRole(user: AuthUserSummary | null | undefined): Role {
  // Back-compat: older session payloads didn't carry role. Treat
  // is_admin → admin, otherwise editor (the pre-role default).
  const r = user?.role
  if (r === 'admin' || r === 'editor' || r === 'viewer') return r
  return user?.is_admin ? 'admin' : 'editor'
}

export function isViewer(user: AuthUserSummary | null | undefined): boolean {
  return userRole(user) === 'viewer'
}

export function canWrite(user: AuthUserSummary | null | undefined): boolean {
  const r = userRole(user)
  return r === 'admin' || r === 'editor'
}

/**
 * True when `path` is inside the user's page_scope (or when they have no
 * scope restriction at all). Scope entries are matched as route prefixes.
 *
 * Exact-match and true-prefix are both accepted. A prefix entry of
 * `/division/product-engineering` lets through:
 *   `/division/product-engineering`
 *   `/division/product-engineering/firmware`
 * but not:
 *   `/division/product-engineeringgg` (hard boundary at the path segment)
 */
export function pathInScope(user: AuthUserSummary | null | undefined, path: string): boolean {
  const scope = user?.page_scope
  if (!scope || scope.length === 0) return true
  for (const entry of scope) {
    if (path === entry) return true
    if (path.startsWith(entry + '/')) return true
  }
  return false
}

/** The first allowed path for this user — their "home" if they land on an
 *  out-of-scope URL. Falls back to '/' when they have no restriction. */
export function defaultAllowedPath(user: AuthUserSummary | null | undefined): string {
  const scope = user?.page_scope
  if (!scope || scope.length === 0) return '/'
  return scope[0]
}
