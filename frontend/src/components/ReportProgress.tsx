import { useState } from 'react'
import type { FormEvent } from 'react'

import { api } from '../api/client'
import type { Operation, ProgressResult } from '../api/types'
import { useAuth } from '../auth/useAuth'
import { useSubmit } from '../lib/useSubmit'
import { ErrorBox } from './ErrorBox'

/**
 * B8 / D-15: a report adds good and rejected deltas. Whether they fit the limit, and
 * whether a negative delta is allowed, is decided by the server (BR-OP-02, BR-OP-03).
 */
export function ReportProgress({ operation, onDone }: { operation: Operation; onDone: () => void }) {
  const { can } = useAuth()
  const [good, setGood] = useState('')
  const [rejected, setRejected] = useState('')
  const [reason, setReason] = useState('')
  const report = useSubmit(async (body: Record<string, unknown>, key: string) => {
    const response = await api.post<ProgressResult>(
      `/production-operations/${operation.id}/progress`,
      body,
      { headers: { 'Idempotency-Key': key } },
    )
    return response.data
  })

  async function onSubmit(event: FormEvent) {
    event.preventDefault()
    const done = await report.submit({
      good_delta: Number(good || 0),
      rejected_delta: Number(rejected || 0),
      ...(reason ? { reason } : {}),
    })
    if (done) {
      setGood('')
      setRejected('')
      setReason('')
      onDone()
    }
  }

  return (
    <form className="row" onSubmit={onSubmit} aria-label={`Báo tiến độ công đoạn ${operation.sequence}`}>
      <label>
        Đạt
        <input value={good} onChange={(e) => setGood(e.target.value)} inputMode="numeric" size={6} />
      </label>
      <label>
        Lỗi
        <input value={rejected} onChange={(e) => setRejected(e.target.value)} inputMode="numeric" size={6} />
      </label>
      {can('operation:correct') && (
        <label>
          Lý do (khi điều chỉnh âm)
          <input value={reason} onChange={(e) => setReason(e.target.value)} maxLength={500} />
        </label>
      )}
      <button type="submit" className="primary" disabled={report.busy}>
        Báo
      </button>
      <ErrorBox error={report.error} />
    </form>
  )
}
