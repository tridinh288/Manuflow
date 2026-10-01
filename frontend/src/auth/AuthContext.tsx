import { useCallback, useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'

import { api, setUnauthorizedHandler, tokenStore } from '../api/client'
import type { Me, Token } from '../api/types'
import { AuthContext, type AuthState } from './useAuth'

export function AuthProvider({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<Me | null>(null)
  // Without a stored token there is nothing to restore.
  const [ready, setReady] = useState(() => tokenStore.get() === null)

  const logout = useCallback(() => {
    tokenStore.clear()
    setMe(null)
  }, [])

  useEffect(() => {
    setUnauthorizedHandler(logout)
    if (tokenStore.get() === null) return
    api
      .get<Me>('/auth/me')
      .then((response) => setMe(response.data))
      .catch(() => tokenStore.clear())
      .finally(() => setReady(true))
  }, [logout])

  const login = useCallback(async (username: string, password: string) => {
    const token = await api.post<Token>('/auth/login', { username, password })
    tokenStore.set(token.data.access_token)
    const profile = await api.get<Me>('/auth/me')
    setMe(profile.data)
  }, [])

  const value = useMemo<AuthState>(
    () => ({
      me,
      ready,
      login,
      logout,
      can: (permission) => me?.permissions.includes(permission) ?? false,
    }),
    [me, ready, login, logout],
  )
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
