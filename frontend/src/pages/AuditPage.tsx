import { useState } from 'react'

import { AuditActionValues, AuditEntityValues } from '../api/enums'
import type { AuditLog, Page } from '../api/types'
import { ErrorBox } from '../components/ErrorBox'
import { formatDate } from '../lib/format'
import { useApi } from '../lib/useApi'

const PAGE = 50

/** BR-AUD-06: ADMIN reads the audit log, filtered on the server. */
export function AuditPage() {
  const [entity, setEntity] = useState('')
  const [action, setAction] = useState('')
  const [actor, setActor] = useState('')
  const [from, setFrom] = useState('')
  const [to, setTo] = useState('')
  const [offset, setOffset] = useState(0)
  const params: Record<string, unknown> = { limit: PAGE, offset }
  if (entity) params.entity_type = entity
  if (action) params.action = action
  if (actor) params.actor_username = actor
  // D-23: the API wants timezone-aware datetimes.
  if (from) params.created_from = new Date(from).toISOString()
  if (to) params.created_to = new Date(to).toISOString()
  const logs = useApi<Page<AuditLog>>('/audit-logs', params)
  const filter = (set: (value: string) => void) => (value: string) => {
    set(value)
    setOffset(0)
  }

  return (
    <div className="stack">
      <h1>Audit log</h1>
      <section>
        <div className="row">
          <label>
            Đối tượng
            <select value={entity} onChange={(e) => filter(setEntity)(e.target.value)}>
              <option value="">Tất cả</option>
              {AuditEntityValues.map((v) => (
                <option key={v}>{v}</option>
              ))}
            </select>
          </label>
          <label>
            Hành động
            <select value={action} onChange={(e) => filter(setAction)(e.target.value)}>
              <option value="">Tất cả</option>
              {AuditActionValues.map((v) => (
                <option key={v}>{v}</option>
              ))}
            </select>
          </label>
          <label>
            Người thực hiện
            <input value={actor} onChange={(e) => filter(setActor)(e.target.value)} maxLength={64} />
          </label>
          <label>
            Từ
            <input type="datetime-local" value={from} onChange={(e) => filter(setFrom)(e.target.value)} />
          </label>
          <label>
            Đến (không gồm)
            <input type="datetime-local" value={to} onChange={(e) => filter(setTo)(e.target.value)} />
          </label>
        </div>
        <ErrorBox error={logs.error} onRetry={logs.reload} />
        <table>
          <thead>
            <tr>
              <th>Thời điểm</th>
              <th>Người</th>
              <th>Hành động</th>
              <th>Đối tượng</th>
              <th>Trước</th>
              <th>Sau</th>
              <th>Lý do</th>
            </tr>
          </thead>
          <tbody>
            {logs.data?.items.map((row) => (
              <tr key={row.id}>
                <td>{formatDate(row.created_at)}</td>
                <td>{row.actor_username ?? '—'}</td>
                <td>{row.action}</td>
                <td>
                  {row.entity_type} #{row.entity_id ?? '—'}
                </td>
                <td>
                  <pre>{row.old_value ? JSON.stringify(row.old_value) : ''}</pre>
                </td>
                <td>
                  <pre>{row.new_value ? JSON.stringify(row.new_value) : ''}</pre>
                </td>
                <td>{row.reason ?? ''}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {logs.data && (
          <div className="row">
            <span className="muted">
              {logs.data.total === 0 ? 0 : offset + 1}–{Math.min(offset + PAGE, logs.data.total)} / {logs.data.total}
            </span>
            <button disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))}>
              Trước
            </button>
            <button disabled={offset + PAGE >= logs.data.total} onClick={() => setOffset(offset + PAGE)}>
              Sau
            </button>
          </div>
        )}
      </section>
    </div>
  )
}
