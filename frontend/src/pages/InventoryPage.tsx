import { useState } from 'react'
import type { FormEvent } from 'react'

import { api, idem } from '../api/client'
import type { Balance, LedgerLine, Movement, Order, OrderMaterial, Page } from '../api/types'
import { useAuth } from '../auth/useAuth'
import { ErrorBox } from '../components/ErrorBox'
import { MoveStock } from '../components/MoveStock'
import { formatDate } from '../lib/format'
import { useApi } from '../lib/useApi'
import { useSubmit } from '../lib/useSubmit'

export function InventoryPage() {
  const { can } = useAuth()
  const [lowOnly, setLowOnly] = useState(false)
  const [ledgerMaterial, setLedgerMaterial] = useState('')
  const balances = useApi<Page<Balance>>('/inventory', { limit: 200, ...(lowOnly ? { low_stock: true } : {}) })
  const ledger = useApi<Page<LedgerLine>>('/inventory/transactions', {
    limit: 50,
    ...(ledgerMaterial ? { material_id: Number(ledgerMaterial) } : {}),
  })
  const refresh = () => {
    balances.reload()
    ledger.reload()
  }

  return (
    <div className="stack">
      <h1>Tồn kho</h1>

      <section>
        <div className="row">
          <h2>Số dư</h2>
          <label className="row">
            <input type="checkbox" checked={lowOnly} onChange={(e) => setLowOnly(e.target.checked)} /> Chỉ tồn thấp
          </label>
        </div>
        <ErrorBox error={balances.error} onRetry={balances.reload} />
        <table>
          <thead>
            <tr>
              <th>Vật tư</th>
              <th>Tồn thực</th>
              <th>Đang giữ</th>
              <th>Khả dụng</th>
              <th>Tối thiểu</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {balances.data?.items.map((b) => (
              <tr key={b.material_id} className={b.low_stock ? 'flagged' : undefined}>
                <td>
                  {b.material_code} · {b.material_name}
                </td>
                <td>
                  {b.on_hand_quantity} {b.unit}
                </td>
                <td>{b.reserved_quantity}</td>
                <td>{b.available_quantity}</td>
                <td>{b.minimum_stock}</td>
                <td>{b.low_stock && <span className="badge AT_RISK">TỒN THẤP</span>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      {(can('inventory:receive') || can('inventory:adjust')) && balances.data && (
        <StockForms balances={balances.data.items} onDone={refresh} />
      )}
      {(can('inventory:issue') || can('inventory:return')) && <OrderMovements onDone={refresh} />}

      <section>
        <div className="row">
          <h2>Sổ cái</h2>
          <label>
            Vật tư
            <select value={ledgerMaterial} onChange={(e) => setLedgerMaterial(e.target.value)}>
              <option value="">Tất cả</option>
              {balances.data?.items.map((b) => (
                <option key={b.material_id} value={b.material_id}>
                  {b.material_code}
                </option>
              ))}
            </select>
          </label>
        </div>
        <ErrorBox error={ledger.error} />
        <table>
          <thead>
            <tr>
              <th>Thời điểm</th>
              <th>Loại</th>
              <th>Vật tư</th>
              <th>Δ tồn thực</th>
              <th>Δ đang giữ</th>
              <th>Sau</th>
              <th>Người làm</th>
              <th>Ghi chú</th>
            </tr>
          </thead>
          <tbody>
            {ledger.data?.items.map((t) => (
              <tr key={t.id}>
                <td>{formatDate(t.created_at)}</td>
                <td>{t.type}</td>
                <td>{t.material_code}</td>
                <td>{t.on_hand_delta}</td>
                <td>{t.reserved_delta}</td>
                <td>
                  {t.on_hand_after} / {t.reserved_after}
                </td>
                <td>{t.created_by}</td>
                <td>{t.reference ?? t.reason ?? ''}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </div>
  )
}

function StockForms({ balances, onDone }: { balances: Balance[]; onDone: () => void }) {
  const { can } = useAuth()
  const [material, setMaterial] = useState('')
  const [quantity, setQuantity] = useState('')
  const [text, setText] = useState('')
  const [last, setLast] = useState<Movement | null>(null)
  const move = useSubmit(async ({ kind, body }: { kind: 'receipts' | 'adjustments'; body: Record<string, unknown> }, key: string) =>
    (await api.post<Movement>(`/inventory/${kind}`, body, idem(key))).data,
  )

  async function send(kind: 'receipts' | 'adjustments') {
    const body =
      kind === 'receipts'
        ? { material_id: Number(material), quantity, ...(text ? { reference: text } : {}) }
        : { material_id: Number(material), quantity_delta: quantity, reason: text }
    const result = await move.submit({ kind, body })
    if (result) {
      setLast(result)
      setQuantity('')
      setText('')
      onDone()
    }
  }

  return (
    <section>
      <h2>Nhập kho / điều chỉnh</h2>
      <form className="row" onSubmit={(e: FormEvent) => e.preventDefault()}>
        <label>
          Vật tư
          <select value={material} onChange={(e) => setMaterial(e.target.value)} required>
            <option value="">Chọn…</option>
            {balances.map((b) => (
              <option key={b.material_id} value={b.material_id}>
                {b.material_code} ({b.unit})
              </option>
            ))}
          </select>
        </label>
        <label>
          Số lượng (điều chỉnh: có dấu, ví dụ -5)
          <input value={quantity} onChange={(e) => setQuantity(e.target.value)} required />
        </label>
        <label>
          Số chứng từ / lý do
          <input value={text} onChange={(e) => setText(e.target.value)} maxLength={500} />
        </label>
        {can('inventory:receive') && (
          <button className="primary" disabled={move.busy || !material} onClick={() => send('receipts')}>
            Nhập kho
          </button>
        )}
        {can('inventory:adjust') && (
          <button disabled={move.busy || !material} onClick={() => send('adjustments')}>
            Điều chỉnh
          </button>
        )}
      </form>
      <ErrorBox error={move.error} />
      {last && (
        <p className="muted" role="status">
          {last.type} {last.material_code}: {last.on_hand_delta} {last.unit} → tồn {last.on_hand_quantity}, khả dụng{' '}
          {last.available_quantity}
        </p>
      )}
    </section>
  )
}

/** Issue to / return from an order line, chosen by order (B6). */
function OrderMovements({ onDone }: { onDone: () => void }) {
  const orders = useApi<Page<Order>>('/production-orders', { limit: 200 })
  const [orderId, setOrderId] = useState('')
  const lines = useApi<Page<OrderMaterial>>(orderId ? `/production-orders/${orderId}/materials` : null)
  return (
    <section>
      <h2>Xuất / trả theo lệnh</h2>
      <label>
        Lệnh
        <select value={orderId} onChange={(e) => setOrderId(e.target.value)}>
          <option value="">Chọn…</option>
          {orders.data?.items.map((o) => (
            <option key={o.id} value={o.id}>
              {o.order_number} · {o.product_code} · {o.status}
            </option>
          ))}
        </select>
      </label>
      <ErrorBox error={lines.error} />
      <table>
        <tbody>
          {lines.data?.items.map((line) => (
            <tr key={line.id}>
              <td>{line.material_code}</td>
              <td>
                giữ {line.reserved_quantity} · xuất {line.issued_quantity} · trả {line.returned_quantity}
              </td>
              <td>
                <MoveStock
                  line={line}
                  onDone={() => {
                    lines.reload()
                    onDone()
                  }}
                />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  )
}
