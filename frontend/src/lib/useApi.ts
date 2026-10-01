import { useCallback, useEffect, useState } from 'react'

import { api } from '../api/client'
import { describeError, type ApiError } from './errors'

type Result<T> = { key: string; data: T | null; error: ApiError | null }

/** GET a resource; `reload` refetches after an action changed it. */
export function useApi<T>(path: string | null, params?: Record<string, unknown>) {
  const [version, setVersion] = useState(0)
  const [result, setResult] = useState<Result<T> | null>(null)
  const query = JSON.stringify(params ?? {})
  const key = `${path}?${query}#${version}`

  useEffect(() => {
    if (path === null) return
    let cancelled = false
    api
      .get<T>(path, { params: JSON.parse(query) as Record<string, unknown> })
      .then((response) => {
        if (!cancelled) setResult({ key, data: response.data, error: null })
      })
      .catch((caught: unknown) => {
        if (!cancelled) setResult({ key, data: null, error: describeError(caught) })
      })
    return () => {
      cancelled = true
    }
  }, [path, query, key])

  const reload = useCallback(() => setVersion((v) => v + 1), [])
  // Keep showing the previous data while a reload is in flight.
  return {
    data: result?.data ?? null,
    error: result?.key === key ? result.error : null,
    loading: path !== null && result?.key !== key,
    reload,
  }
}
