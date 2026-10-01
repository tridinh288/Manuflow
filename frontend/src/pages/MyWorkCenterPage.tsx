import type { Operations, Order, Page } from '../api/types'
import { ErrorBox } from '../components/ErrorBox'
import { ReportProgress } from '../components/ReportProgress'
import { formatDate } from '../lib/format'
import { useApi } from '../lib/useApi'

/**
 * B17 "Work center của tôi": the server already limits a WORKER to orders and operations
 * at their own work center (BR-AUTH-03), so this page only lists what it is given.
 */
export function MyWorkCenterPage() {
  const orders = useApi<Page<Order>>('/production-orders', { status: 'IN_PROGRESS', limit: 200 })
  return (
    <div className="stack">
      <h1>Work center của tôi</h1>
      <ErrorBox error={orders.error} onRetry={orders.reload} />
      {orders.data?.items.length === 0 && (
        <section>
          <p className="muted">Không có lệnh nào đang sản xuất tại work center của bạn.</p>
        </section>
      )}
      {orders.data?.items.map((order) => (
        <OrderOperations key={order.id} order={order} />
      ))}
    </div>
  )
}

function OrderOperations({ order }: { order: Order }) {
  const operations = useApi<Operations>(`/production-orders/${order.id}/operations`)
  return (
    <section>
      <h2>
        {order.order_number} · {order.product_code} × {order.planned_quantity}
      </h2>
      <p className="muted">Hạn giao {formatDate(order.due_date)}</p>
      <ErrorBox error={operations.error} onRetry={operations.reload} />
      <table>
        <thead>
          <tr>
            <th>#</th>
            <th>Công đoạn</th>
            <th>Trạng thái</th>
            <th>Đạt / lỗi</th>
            <th>Đã xử lý / giới hạn</th>
            <th>Báo tiến độ</th>
          </tr>
        </thead>
        <tbody>
          {operations.data?.items.map((op) => (
            <tr key={op.id}>
              <td>{op.sequence}</td>
              <td>
                {op.operation_type} @ {op.work_center_code}
              </td>
              <td>{op.status}</td>
              <td>
                {op.good_quantity} / {op.rejected_quantity}
              </td>
              <td>
                {op.processed_quantity} / {op.limit}
              </td>
              <td>
                {op.status !== 'COMPLETED' && <ReportProgress operation={op} onDone={operations.reload} />}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  )
}
