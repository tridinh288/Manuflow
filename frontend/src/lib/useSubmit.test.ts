import { act, renderHook } from '@testing-library/react'
import { AxiosError, AxiosHeaders } from 'axios'

import { useSubmit } from './useSubmit'

function httpError(status: number, code = 'SOME_ERROR'): AxiosError {
  const config = { headers: new AxiosHeaders() }
  return new AxiosError('failed', String(status), config, null, {
    status,
    statusText: '',
    headers: {},
    config,
    data: { error: { code, message: code, details: [], request_id: 'r' } },
  })
}

const networkError = () => new AxiosError('Network Error', 'ERR_NETWORK')

function setup(outcomes: Array<'ok' | 'network' | 503 | 409>) {
  const keys: string[] = []
  const send = vi.fn(async (_payload: { q: string }, key: string) => {
    keys.push(key)
    const outcome = outcomes[keys.length - 1]
    if (outcome === 'network') throw networkError()
    if (typeof outcome === 'number') throw httpError(outcome)
    return 'done'
  })
  const { result } = renderHook(() => useSubmit(send))
  return { keys, submit: (q: string) => act(() => result.current.submit({ q })), result }
}

describe('B17 / D-22: one Idempotency-Key per submission, reused on retry', () => {
  it('reuses the key when the same payload is retried after a network failure or a 5xx', async () => {
    const { keys, submit } = setup(['network', 503, 'ok'])
    await submit('10')
    await submit('10')
    await submit('10')
    expect(new Set(keys).size).toBe(1)
  })

  it('takes a new key for the next submission once one succeeded', async () => {
    const { keys, submit } = setup(['ok', 'ok'])
    await submit('10')
    await submit('10')
    expect(keys[0]).not.toBe(keys[1])
  })

  it('takes a new key after a definitive 4xx answer', async () => {
    const { keys, submit, result } = setup([409, 'ok'])
    await submit('10')
    expect(result.current.error?.code).toBe('SOME_ERROR')
    expect(result.current.error?.retryable).toBe(false)
    await submit('10')
    expect(keys[0]).not.toBe(keys[1])
  })

  it('takes a new key when the payload changed, since a reused key with another body is a 422', async () => {
    const { keys, submit } = setup(['network', 'ok'])
    await submit('10')
    await submit('12')
    expect(keys[0]).not.toBe(keys[1])
  })
})
