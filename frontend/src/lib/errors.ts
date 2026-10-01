import axios from 'axios'

import type { ApiErrorBody } from '../api/types'

export type ApiError = {
  code: string
  message: string
  details: unknown[]
  status: number | null
  /** The outcome is unknown (network failure, 5xx): the same request may be retried. */
  retryable: boolean
}

function isErrorBody(data: unknown): data is ApiErrorBody {
  return typeof data === 'object' && data !== null && 'error' in data
}

/** Maps any failure to the B13 error shape; messages come from the API, not the UI. */
export function describeError(error: unknown): ApiError {
  if (axios.isAxiosError(error)) {
    const status = error.response?.status ?? null
    const data: unknown = error.response?.data
    if (isErrorBody(data)) {
      return {
        code: data.error.code,
        message: data.error.message,
        details: data.error.details,
        status,
        retryable: status !== null && status >= 500,
      }
    }
    if (status === null) {
      return {
        code: 'NETWORK_ERROR',
        message: 'Không kết nối được tới máy chủ. Hãy thử lại.',
        details: [],
        status,
        retryable: true,
      }
    }
    return { code: 'HTTP_ERROR', message: error.message, details: [], status, retryable: status >= 500 }
  }
  return { code: 'UNKNOWN', message: String(error), details: [], status: null, retryable: false }
}
