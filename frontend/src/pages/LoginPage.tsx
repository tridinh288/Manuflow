import { useState } from 'react'
import type { FormEvent } from 'react'
import { Navigate } from 'react-router-dom'

import { useAuth } from '../auth/useAuth'
import { ErrorBox } from '../components/ErrorBox'
import { describeError, type ApiError } from '../lib/errors'

export function LoginPage() {
  const { me, login } = useAuth()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<ApiError | null>(null)
  const [busy, setBusy] = useState(false)

  if (me !== null) return <Navigate to="/" replace />

  async function onSubmit(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await login(username, password)
    } catch (caught) {
      // BR-AUTH-05: the API returns one generic message for every failure; show it as is.
      setError(describeError(caught))
    } finally {
      setBusy(false)
    }
  }

  return (
    <form className="login" onSubmit={onSubmit}>
      <h1>Manuflow</h1>
      <label>
        Tên đăng nhập
        <input value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" required />
      </label>
      <label>
        Mật khẩu
        <input
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          autoComplete="current-password"
          required
        />
      </label>
      <button type="submit" disabled={busy}>
        Đăng nhập
      </button>
      <ErrorBox error={error} />
    </form>
  )
}
