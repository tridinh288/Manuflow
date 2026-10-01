import { useCallback, useRef, useState } from 'react'

import { describeError, type ApiError } from './errors'

export function newIdempotencyKey(): string {
  return crypto.randomUUID()
}

type Pending = { key: string; payload: string }

/**
 * B17 / D-22: every form submission gets a fresh Idempotency-Key, and a retry of the same
 * submission reuses it, so a double click or a retry after a timeout never repeats the
 * change. The key is dropped once the server has answered definitively (success or a 4xx)
 * or when the payload changes, because a reused key with another body is a 422.
 */
export function useSubmit<P, R>(send: (payload: P, idempotencyKey: string) => Promise<R>) {
  const pending = useRef<Pending | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<ApiError | null>(null)

  const submit = useCallback(
    async (payload: P): Promise<R | undefined> => {
      const body = JSON.stringify(payload)
      if (pending.current === null || pending.current.payload !== body) {
        pending.current = { key: newIdempotencyKey(), payload: body }
      }
      setBusy(true)
      setError(null)
      try {
        const result = await send(payload, pending.current.key)
        pending.current = null
        return result
      } catch (caught) {
        const described = describeError(caught)
        if (!described.retryable) pending.current = null
        setError(described)
        return undefined
      } finally {
        setBusy(false)
      }
    },
    [send],
  )

  return { submit, busy, error, clearError: () => setError(null) }
}
