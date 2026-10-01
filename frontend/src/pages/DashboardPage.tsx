import type { Bottleneck, MaterialAlerts, OrderRisk, Page, ProductionOverview } from '../api/types'
import { ErrorBox } from '../components/ErrorBox'
import { formatDate, percent } from '../lib/format'
import { useApi } from '../lib/useApi'

export function DashboardPage() {
  const overview = useApi<ProductionOverview>('/dashboard/production')
  const risks = useApi<Page<OrderRisk>>('/dashboard/risks')
  const bottlenecks = useApi<Page<Bottleneck>>('/dashboard/bottlenecks')
  const alerts = useApi<MaterialAlerts>('/dashboard/material-alerts')

  return (
    <div className="stack">
      <h1>Dashboard</h1>

      <section>
        <h2>Lệnh theo trạng thái</h2>
        <ErrorBox error={overview.error} />
        {overview.data && (
          <div className="cards">
            {Object.entries(overview.data.orders_by_status).map(([status, count]) => (
              <div key={status} className="card">
                <span className="muted">{status}</span>
                <strong>{count}</strong>
              </div>
            ))}
          </div>
        )}
      </section>

      <section>
        <h2>Rủi ro</h2>
        <ErrorBox error={risks.error} />
        <table>
          <thead>
            <tr>
              <th>Lệnh</th>
              <th>Sản phẩm</th>
              <th>Rủi ro</th>
              <th>Hạn</th>
              <th>Thời gian</th>
              <th>Quy trình</th>
              <th>Công đoạn hiện tại</th>
              <th>Lý do</th>
            </tr>
          </thead>
          <tbody>
            {risks.data?.items.map((r) => (
              <tr key={r.order_id}>
                <td>{r.production_order}</td>
                <td>{r.product_code}</td>
                <td>
                  <span className={`badge ${r.risk}`}>{r.risk}</span>
                </td>
                <td>{formatDate(r.due_date)}</td>
                <td>{percent(r.time_ratio)}</td>
                <td>{percent(r.workflow_progress)}</td>
                <td>
                  {r.current_operation
                    ? `${r.current_operation.type} @ ${r.current_operation.work_center}`
                    : '—'}
                </td>
                <td>{r.message}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {risks.data?.items.length === 0 && <p className="muted">Không có lệnh nào có rủi ro.</p>}
      </section>

      <section>
        <h2>Điểm nghẽn</h2>
        <ErrorBox error={bottlenecks.error} />
        <table>
          <thead>
            <tr>
              <th>Work center</th>
              <th>Hàng đợi (đơn vị)</th>
              <th>Lệnh rủi ro</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {bottlenecks.data?.items.map((b) => (
              <tr key={b.work_center_id} className={b.bottleneck ? 'flagged' : undefined}>
                <td>{b.work_center}</td>
                <td>{b.queue_units}</td>
                <td>{b.at_risk_orders}</td>
                <td>{b.bottleneck && <span className="badge AT_RISK">BOTTLENECK</span>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section>
        <h2>Cảnh báo vật tư</h2>
        <ErrorBox error={alerts.error} />
        <h3>Dưới mức tối thiểu</h3>
        <table>
          <thead>
            <tr>
              <th>Vật tư</th>
              <th>Khả dụng</th>
              <th>Tối thiểu</th>
              <th>Thiếu so với tối thiểu</th>
            </tr>
          </thead>
          <tbody>
            {alerts.data?.low_stock.map((m) => (
              <tr key={m.material_id}>
                <td>{m.material_code}</td>
                <td>
                  {m.available_quantity} {m.unit}
                </td>
                <td>
                  {m.minimum_stock} {m.unit}
                </td>
                <td>
                  {m.below_minimum_by} {m.unit}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <h3>Lệnh thiếu hàng nên kiểm tra lại</h3>
        {alerts.data?.recheck_candidates.length === 0 && <p className="muted">Không có.</p>}
        <ul>
          {alerts.data?.recheck_candidates.map((o) => (
            <li key={o.order_id}>
              {o.production_order} ({o.product_code})
            </li>
          ))}
        </ul>
      </section>

      <section>
        <h2>Đến hạn trong 7 ngày</h2>
        <ul>
          {overview.data?.due_within_7_days.map((o) => (
            <li key={o.order_id}>
              {o.production_order} · {o.product_code} · {o.status} · {formatDate(o.due_date)}
            </li>
          ))}
        </ul>
      </section>
    </div>
  )
}
