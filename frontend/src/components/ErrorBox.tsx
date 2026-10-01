import type { ApiError } from '../lib/errors'

/** Shows the API's own error code and message (B13); the UI adds no rules of its own. */
export function ErrorBox({ error, onRetry }: { error: ApiError | null; onRetry?: () => void }) {
  if (error === null) return null
  return (
    <div role="alert" className="error">
      <strong>{error.code}</strong>: {error.message}
      {error.details.length > 0 && <pre>{JSON.stringify(error.details, null, 2)}</pre>}
      {error.retryable && onRetry && (
        <button type="button" onClick={onRetry}>
          Thử lại
        </button>
      )}
    </div>
  )
}
