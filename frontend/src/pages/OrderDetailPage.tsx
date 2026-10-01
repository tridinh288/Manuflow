import { useState } from 'react'
import type { FormEvent } from 'react'
import { useParams } from 'react-router-dom'

import { api } from '../api/client'
import type { Operations, Order, OrderMaterial, Page, Reservation } from '../api/types'
import { useAuth } from '../auth/useAuth'
import { ErrorBox } from '../components/ErrorBox'
import { ReportProgress } from '../components/ReportProgress'
import { formatDate, percent } from '../lib/format'
import { useApi } from '../lib/useApi'
import { useSubmit } from '../lib/useSubmit'

const ACTION_LABELS: Record<string, string> = {
  plan: 'Lập kế hoạch (giữ hàng)',
  'check-materials': 'Kiểm tra lại vật tư',
  start: 'Bắt đầu sản xuất',
  cancel: 'Hủy lệnh',
  update: 'Sửa lệnh',
}

type ActionCall = { action: string; body?: Record<string, unknown> }

/** plan and check-materials answer with the material check (B6); other actions do not. */
function isReservation(result: Order | Reservation): result is Reservation {
  return 'reserved' in result
}

export function OrderDetailPage() {
  const id = Number(useParams().id)
  const { can } = useAuth()
  const order = useApi<Order>(`/production-orders/${id}`)
  const materials = useApi<Page<OrderMaterial>>(`/production-orders/${id}/materials`)
  const operations = useApi<Operations>(`/production-orders/${id}/operations`)
  const [check, setCheck] = useState<Reservation | null>(null)
  const [cancelling, setCancelling] = useState(false)

  const reloadAll = () => {
    order.reload()
    materials.reload()
    operations.reload()
  }

  const act = useSubmit(async ({ action, body }: ActionCall, key: string) => {
    const headers = { 'Idempotency-Key': key }
    const response =
      action === 'update'
        ? await api.patch<Order>(`/production-orders/${id}`, body, { headers })
        : await api.post<Order | Reservation>(`/production-orders/${id}/${action}`, body ?? {}, { headers })
    return response.data
  })

  async function run(call: ActionCall) {
    const result = await act.submit(call)
    if (result === undefined) return
    setCheck(isReservation(result) ? result : null)
    setCancelling(false)
    reloadAll()
  }

  if (order.error) return <ErrorBox error={order.error} />
  const o = order.data
  if (o === null) return <p className="muted">Đang tải…</p>

  return (
    <div className="stack">
      <h1>
        {o.order_number} · {o.product_code} × {o.planned_quantity}{' '}
        <span className={`badge ${o.status}`}>{o.status}</span>
      </h1>

      <section>
        <p>
          Hạn giao: {formatDate(o.due_date)}
          {o.started_at && ` · Bắt đầu: ${formatDate(o.started_at)}`}
          {o.completed_quantity !== null && ` · Hoàn thành: ${o.completed_quantity}`}
          {o.cancel_reason && ` · Lý do hủy: ${o.cancel_reason}`}
        </p>
        {o.notes && <p className="muted">{o.notes}</p>}
        {/* BR-PO-05: the buttons are exactly the actions the server allows this user now. */}
        <div className="actions">
          {o.allowed_actions
            .filter((a) => a !== 'cancel' && a !== 'update')
            .map((action) => (
              <button key={action} className="primary" disabled={act.busy} onClick={() => run({ action })}>
                {ACTION_LABELS[action] ?? action}
              </button>
            ))}
          {o.allowed_actions.includes('cancel') && (
            <button disabled={act.busy} onClick={() => setCancelling((v) => !v)}>
              {ACTION_LABELS.cancel}
            </button>
          )}
        </div>
        {cancelling && <CancelForm busy={act.busy} onCancel={(reason) => run({ action: 'cancel', body: { reason } })} />}
        {o.allowed_actions.includes('update') && (
          <UpdateForm order={o} busy={act.busy} onSave={(body) => run({ action: 'update', body })} />
        )}
        <ErrorBox error={act.error} />
        {check && !check.reserved && (
          <div className="error" role="status">
            <strong>Thiếu vật tư, chưa giữ hàng nào.</strong>
            <table>
              <thead>
                <tr>
                  <th>Vật tư</th>
                  <th>Cần</th>
                  <th>Khả dụng</th>
                  <th>Thiếu</th>
                </tr>
              </thead>
              <tbody>
                {check.material_check.map((m) => (
                  <tr key={m.material_id}>
                    <td>{m.material_code}</td>
                    <td>
                      {m.required} {m.unit}
                    </td>
                    <td>
                      {m.available} {m.unit}
                    </td>
                    <td>
                      {m.shortage} {m.unit}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section>
        <h2>Vật tư</h2>
        <ErrorBox error={materials.error} />
        <table>
          <thead>
            <tr>
              <th>Vật tư</th>
              <th>Cần</th>
              <th>Đang giữ</th>
              <th>Đã xuất</th>
              <th>Đã trả</th>
              <th>Thiếu</th>
              {(can('inventory:issue') || can('inventory:return')) && <th>Kho</th>}
            </tr>
          </thead>
          <tbody>
            {materials.data?.items.map((m) => (
              <tr key={m.id}>
                <td>{m.material_code}</td>
                <td>
                  {m.required_quantity} {m.unit}
                </td>
                <td>{m.reserved_quantity}</td>
                <td>{m.issued_quantity}</td>
                <td>{m.returned_quantity}</td>
                <td>{m.shortage_quantity}</td>
                {(can('inventory:issue') || can('inventory:return')) && (
                  <td>
                    <MoveStock line={m} onDone={reloadAll} />
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section>
        <h2>Công đoạn</h2>
        <ErrorBox error={operations.error} />
        {operations.data && (
          <p className="muted">
            Tiến độ quy trình {percent(operations.data.workflow_progress)} · thành phẩm{' '}
            {percent(operations.data.finished_progress)}
          </p>
        )}
        <table>
          <thead>
            <tr>
              <th>#</th>
              <th>Công đoạn</th>
              <th>Work center</th>
              <th>Trạng thái</th>
              <th>Đạt / lỗi</th>
              <th>Đã xử lý / giới hạn</th>
              <th>Tiến độ</th>
              {can('operation:report') && o.status === 'IN_PROGRESS' && <th>Báo</th>}
            </tr>
          </thead>
          <tbody>
            {operations.data?.items.map((op) => (
              <tr key={op.id}>
                <td>{op.sequence}</td>
                <td>{op.operation_type}</td>
                <td>{op.work_center_code}</td>
                <td>{op.status}</td>
                <td>
                  {op.good_quantity} / {op.rejected_quantity}
                </td>
                <td>
                  {op.processed_quantity} / {op.limit}
                </td>
                <td>{percent(op.progress)}</td>
                {can('operation:report') && o.status === 'IN_PROGRESS' && (
                  <td>
                    <ReportProgress operation={op} onDone={reloadAll} />
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </div>
  )
}

function CancelForm({ busy, onCancel }: { busy: boolean; onCancel: (reason: string) => void }) {
  const [reason, setReason] = useState('')
  return (
    <form
      className="row"
      onSubmit={(e: FormEvent) => {
        e.preventDefault()
        onCancel(reason)
      }}
    >
      <label>
        Lý do hủy
        <input value={reason} onChange={(e) => setReason(e.target.value)} required maxLength={500} />
      </label>
      <button type="submit" disabled={busy}>
        Xác nhận hủy
      </button>
    </form>
  )
}

function UpdateForm({
  order,
  busy,
  onSave,
}: {
  order: Order
  busy: boolean
  onSave: (body: Record<string, unknown>) => void
}) {
  const [quantity, setQuantity] = useState(String(order.planned_quantity))
  const [notes, setNotes] = useState(order.notes ?? '')
  return (
    <form
      className="row"
      onSubmit={(e: FormEvent) => {
        e.preventDefault()
        onSave({ planned_quantity: Number(quantity), notes: notes || null })
      }}
    >
      <label>
        Số lượng
        <input value={quantity} onChange={(e) => setQuantity(e.target.value)} inputMode="numeric" />
      </label>
      <label>
        Ghi chú
        <input value={notes} onChange={(e) => setNotes(e.target.value)} maxLength={1000} />
      </label>
      <button type="submit" disabled={busy}>
        {ACTION_LABELS.update}
      </button>
    </form>
  )
}

/** ISSUE / RETURN for one order line; the server checks D-10 and the returnable amount. */
function MoveStock({ line, onDone }: { line: OrderMaterial; onDone: () => void }) {
  const { can } = useAuth()
  const [quantity, setQuantity] = useState('')
  const move = useSubmit(async ({ kind, qty }: { kind: 'issues' | 'returns'; qty: string }, key: string) => {
    const response = await api.post(
      `/inventory/${kind}`,
      { order_material_id: line.id, quantity: qty },
      { headers: { 'Idempotency-Key': key } },
    )
    return response.data as unknown
  })

  async function send(kind: 'issues' | 'returns', qty: string) {
    if ((await move.submit({ kind, qty })) !== undefined) {
      setQuantity('')
      onDone()
    }
  }

  return (
    <div className="row">
      <input
        value={quantity}
        onChange={(e) => setQuantity(e.target.value)}
        placeholder={line.reserved_quantity}
        aria-label={`Số lượng ${line.material_code}`}
        size={8}
      />
      {can('inventory:issue') && (
        <button disabled={move.busy} onClick={() => send('issues', quantity || line.reserved_quantity)}>
          Xuất
        </button>
      )}
      {can('inventory:return') && (
        <button disabled={move.busy || !quantity} onClick={() => send('returns', quantity)}>
          Trả
        </button>
      )}
      <ErrorBox error={move.error} />
    </div>
  )
}
