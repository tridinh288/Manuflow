import { createContext, useContext } from 'react'

import type { Me } from '../api/types'

export type AuthState = {
  me: Me | null
  ready: boolean
  login: (username: string, password: string) => Promise<void>
  logout: () => void
  /** Menus and buttons follow the permissions the API returns in /auth/me (B17). */
  can: (permission: string) => boolean
}

export const AuthContext = createContext<AuthState | null>(null)

export function useAuth(): AuthState {
  const value = useContext(AuthContext)
  if (value === null) throw new Error('useAuth must be used inside <AuthProvider>')
  return value
}
