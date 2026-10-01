import { useState } from 'react'
import type { FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'

import { api } from '../api/client'
import type { Order, OrderStatus, Page, Product } from '../api/types'
import { useAuth } from '../auth/useAuth'
import { ErrorBox } from '../components/ErrorBox'
import { formatDate } from '../lib/format'
import { useApi } from '../lib/useApi'
import { useSubmit } from '../lib/useSubmit'

const STATUSES: OrderStatus[] = [
  'DRAFT',
  'MATERIAL_SHORTAGE',
  'READY_TO_PRODUCE',
  'IN_PROGRESS',
  'COMPLETED',
  'CANCELLED',
]

export function OrdersPage() {
  const { can } = useAuth()
  const [status, setStatus] = useState('')
  const orders = useApi<Page<Order>>('/production-orders', {
    limit: 200,
    ...(status ? { status } : {}),
  })

  return (
    <div className="stack">
      <h1>Lệnh sản xuất</h1>
      {can('order:create') && <CreateOrder />}
      <section>
        <div className="row">
          <label>
            Trạng thái
            <select value={status} onChange={(e) => setStatus(e.target.value)}>
              <option value="">Tất cả</option>
              {STATUSES.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </label>
          <span className="muted">{orders.data ? `${orders.data.total} lệnh` : ''}</span>
        </div>
        <ErrorBox error={orders.error} onRetry={orders.reload} />
        <table>
          <thead>
            <tr>
              <th>Lệnh</th>
              <th>Sản phẩm</th>
              <th>Số lượng</th>
              <th>Trạng thái</th>
              <th>Hạn</th>
            </tr>
          </thead>
          <tbody>
            {orders.data?.items.map((o) => (
              <tr key={o.id}>
                <td>
                  <Link to={`/orders/${o.id}`}>{o.order_number}</Link>
                </td>
                <td>{o.product_code}</td>
                <td>
                  {o.planned_quantity}
                  {o.completed_quantity !== null && ` (xong ${o.completed_quantity})`}
                </td>
                <td>
                  <span className={`badge ${o.status}`}>{o.status}</span>
                </td>
                <td>{formatDate(o.due_date)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </div>
  )
}

function CreateOrder() {
  const navigate = useNavigate()
  const products = useApi<Page<Product>>('/products', { limit: 200 })
  const [productId, setProductId] = useState('')
  const [quantity, setQuantity] = useState('')
  const [due, setDue] = useState('')
  const [notes, setNotes] = useState('')
  const create = useSubmit(async (body: Record<string, unknown>, key: string) => {
    const response = await api.post<Order>('/production-orders', body, {
      headers: { 'Idempotency-Key': key },
    })
    return response.data
  })

  async function onSubmit(event: FormEvent) {
    event.preventDefault()
    const order = await create.submit({
      product_id: Number(productId),
      // The server validates the quantity (BR-BOM-05: 0, -1, 1.5 are refused), not the UI.
      planned_quantity: Number(quantity),
      due_date: new Date(due).toISOString(),
      notes: notes || null,
    })
    if (order) navigate(`/orders/${order.id}`)
  }

  return (
    <section>
      <h2>Tạo lệnh</h2>
      <form className="row" onSubmit={onSubmit}>
        <label>
          Sản phẩm
          <select value={productId} onChange={(e) => setProductId(e.target.value)} required>
            <option value="" disabled>
              Chọn…
            </option>
            {products.data?.items
              .filter((p) => p.active)
              .map((p) => (
                <option key={p.id} value={p.id}>
                  {p.product_code} · {p.name}
                </option>
              ))}
          </select>
        </label>
        <label>
          Số lượng
          <input value={quantity} onChange={(e) => setQuantity(e.target.value)} inputMode="numeric" required />
        </label>
        <label>
          Hạn giao
          <input type="datetime-local" value={due} onChange={(e) => setDue(e.target.value)} required />
        </label>
        <label>
          Ghi chú
          <input value={notes} onChange={(e) => setNotes(e.target.value)} maxLength={1000} />
        </label>
        <button type="submit" className="primary" disabled={create.busy}>
          Tạo lệnh
        </button>
      </form>
      <ErrorBox error={create.error} />
    </section>
  )
}
