import { useState } from 'react'
import type { FormEvent } from 'react'

import { api, idem } from '../api/client'
import { OperationTypeValues } from '../api/enums'
import type { Bom, Explosion, Material, OperationType, Page, Product, Routing, WorkCenter } from '../api/types'
import { useAuth } from '../auth/useAuth'
import { ErrorBox } from '../components/ErrorBox'
import { formatDate } from '../lib/format'
import { useApi } from '../lib/useApi'
import { useSubmit } from '../lib/useSubmit'

export function ProductsPage() {
  const { can } = useAuth()
  const products = useApi<Page<Product>>('/products', { limit: 200 })
  const [selected, setSelected] = useState<number | null>(null)
  const product = products.data?.items.find((p) => p.id === selected) ?? null

  return (
    <div className="stack">
      <h1>Sản phẩm · BOM · Routing</h1>
      {can('master:write') && <CreateProduct onCreated={products.reload} />}
      <section>
        <ErrorBox error={products.error} onRetry={products.reload} />
        <table>
          <thead>
            <tr>
              <th>Mã</th>
              <th>Tên</th>
              <th>Trạng thái</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {products.data?.items.map((p) => (
              <tr key={p.id} className={p.id === selected ? 'flagged' : undefined}>
                <td>{p.product_code}</td>
                <td>{p.name}</td>
                <td>{p.active ? 'ACTIVE' : 'INACTIVE'}</td>
                <td>
                  <button onClick={() => setSelected(p.id)}>Xem BOM / routing</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
      {product && <ProductDetail key={product.id} product={product} />}
    </div>
  )
}

function CreateProduct({ onCreated }: { onCreated: () => void }) {
  const [code, setCode] = useState('')
  const [name, setName] = useState('')
  const create = useSubmit(async (body: Record<string, unknown>, key: string) => (await api.post('/products', body, idem(key))).data as unknown)
  async function onSubmit(event: FormEvent) {
    event.preventDefault()
    if ((await create.submit({ product_code: code, name })) !== undefined) {
      setCode('')
      setName('')
      onCreated()
    }
  }
  return (
    <section>
      <h2>Thêm sản phẩm</h2>
      <form className="row" onSubmit={onSubmit}>
        <label>
          Mã
          <input value={code} onChange={(e) => setCode(e.target.value)} required />
        </label>
        <label>
          Tên
          <input value={name} onChange={(e) => setName(e.target.value)} required />
        </label>
        <button className="primary" disabled={create.busy}>
          Thêm
        </button>
      </form>
      <ErrorBox error={create.error} />
    </section>
  )
}

function ProductDetail({ product }: { product: Product }) {
  const { can } = useAuth()
  const boms = useApi<Page<Bom>>(`/products/${product.id}/boms`)
  const routings = useApi<Page<Routing>>(`/products/${product.id}/routings`)
  const versionAction = useSubmit(async (path: string, key: string) => (await api.post(path, {}, idem(key))).data as unknown)

  async function post(path: string, reload: () => void) {
    if ((await versionAction.submit(path)) !== undefined) reload()
  }

  return (
    <>
      <section>
        <h2>BOM của {product.product_code}</h2>
        <ErrorBox error={boms.error ?? versionAction.error} />
        {can('bom:write') && (
          <button onClick={() => post(`/products/${product.id}/boms`, boms.reload)} disabled={versionAction.busy}>
            Tạo phiên bản nháp
          </button>
        )}
        {boms.data?.items.map((bom) => (
          <div key={bom.id}>
            <h3>
              Phiên bản {bom.version} <span className={`badge ${bom.status}`}>{bom.status}</span>
              {bom.activated_at && <span className="muted"> · kích hoạt {formatDate(bom.activated_at)}</span>}
            </h3>
            <table>
              <thead>
                <tr>
                  <th>Vật tư</th>
                  <th>Định mức / đơn vị</th>
                  <th>Tỷ lệ hao hụt</th>
                </tr>
              </thead>
              <tbody>
                {bom.items.map((item) => (
                  <tr key={item.material_id}>
                    <td>{item.material_code}</td>
                    <td>
                      {item.qty_per_unit} {item.unit}
                    </td>
                    <td>{item.scrap_rate}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {bom.status === 'DRAFT' && can('bom:write') && (
              <>
                <BomItemsEditor bom={bom} onSaved={boms.reload} />
                <button className="primary" onClick={() => post(`/boms/${bom.id}/activate`, boms.reload)}>
                  Kích hoạt phiên bản {bom.version}
                </button>
              </>
            )}
          </div>
        ))}
      </section>
      <ExplodePreview product={product} />
      <section>
        <h2>Routing của {product.product_code}</h2>
        <ErrorBox error={routings.error} />
        {can('routing:write') && (
          <button onClick={() => post(`/products/${product.id}/routings`, routings.reload)} disabled={versionAction.busy}>
            Tạo routing nháp
          </button>
        )}
        {routings.data?.items.map((routing) => (
          <div key={routing.id}>
            <h3>
              Phiên bản {routing.version} <span className={`badge ${routing.status}`}>{routing.status}</span>
            </h3>
            <ol>
              {routing.steps.map((step) => (
                <li key={step.sequence}>
                  {step.sequence} · {step.operation_type} @ {step.work_center_code}
                </li>
              ))}
            </ol>
            {routing.status === 'DRAFT' && can('routing:write') && (
              <>
                <RoutingStepsEditor routing={routing} onSaved={routings.reload} />
                <button className="primary" onClick={() => post(`/routings/${routing.id}/activate`, routings.reload)}>
                  Kích hoạt routing {routing.version}
                </button>
              </>
            )}
          </div>
        ))}
      </section>
    </>
  )
}

type ItemRow = { material_id: string; qty_per_unit: string; scrap_rate: string }

function BomItemsEditor({ bom, onSaved }: { bom: Bom; onSaved: () => void }) {
  const materials = useApi<Page<Material>>('/materials', { limit: 200 })
  const [rows, setRows] = useState<ItemRow[]>(
    bom.items.length > 0
      ? bom.items.map((i) => ({ material_id: String(i.material_id), qty_per_unit: i.qty_per_unit, scrap_rate: i.scrap_rate }))
      : [{ material_id: '', qty_per_unit: '', scrap_rate: '0' }],
  )
  const save = useSubmit(async (items: ItemRow[], key: string) =>
    (
      await api.put(
        `/boms/${bom.id}/items`,
        { items: items.map((r) => ({ material_id: Number(r.material_id), qty_per_unit: r.qty_per_unit, scrap_rate: r.scrap_rate })) },
        idem(key),
      )
    ).data as unknown,
  )
  const update = (index: number, patch: Partial<ItemRow>) =>
    setRows((current) => current.map((row, i) => (i === index ? { ...row, ...patch } : row)))

  return (
    <form
      onSubmit={async (e: FormEvent) => {
        e.preventDefault()
        if ((await save.submit(rows)) !== undefined) onSaved()
      }}
    >
      {rows.map((row, index) => (
        <div className="row" key={index}>
          <select value={row.material_id} onChange={(e) => update(index, { material_id: e.target.value })} aria-label="Vật tư">
            <option value="">Vật tư…</option>
            {materials.data?.items.map((m) => (
              <option key={m.id} value={m.id}>
                {m.material_code} ({m.unit})
              </option>
            ))}
          </select>
          <input value={row.qty_per_unit} onChange={(e) => update(index, { qty_per_unit: e.target.value })} placeholder="định mức" aria-label="Định mức" />
          <input value={row.scrap_rate} onChange={(e) => update(index, { scrap_rate: e.target.value })} placeholder="hao hụt" aria-label="Hao hụt" />
        </div>
      ))}
      <div className="actions">
        <button type="button" onClick={() => setRows((r) => [...r, { material_id: '', qty_per_unit: '', scrap_rate: '0' }])}>
          + Dòng
        </button>
        <button type="submit" disabled={save.busy}>
          Lưu định mức
        </button>
      </div>
      <ErrorBox error={save.error} />
    </form>
  )
}

type StepRow = { sequence: string; operation_type: OperationType; work_center_id: string }

function RoutingStepsEditor({ routing, onSaved }: { routing: Routing; onSaved: () => void }) {
  const centers = useApi<Page<WorkCenter>>('/work-centers', { limit: 200 })
  const [rows, setRows] = useState<StepRow[]>(
    routing.steps.length > 0
      ? routing.steps.map((s) => ({ sequence: String(s.sequence), operation_type: s.operation_type as OperationType, work_center_id: String(s.work_center_id) }))
      : [{ sequence: '10', operation_type: 'QC', work_center_id: '' }],
  )
  const save = useSubmit(async (steps: StepRow[], key: string) =>
    (
      await api.put(
        `/routings/${routing.id}/steps`,
        { steps: steps.map((s) => ({ sequence: Number(s.sequence), operation_type: s.operation_type, work_center_id: Number(s.work_center_id) })) },
        idem(key),
      )
    ).data as unknown,
  )
  const update = (index: number, patch: Partial<StepRow>) =>
    setRows((current) => current.map((row, i) => (i === index ? { ...row, ...patch } : row)))

  return (
    <form
      onSubmit={async (e: FormEvent) => {
        e.preventDefault()
        if ((await save.submit(rows)) !== undefined) onSaved()
      }}
    >
      {rows.map((row, index) => (
        <div className="row" key={index}>
          <input value={row.sequence} onChange={(e) => update(index, { sequence: e.target.value })} size={5} aria-label="Thứ tự" />
          <select value={row.operation_type} onChange={(e) => update(index, { operation_type: e.target.value as OperationType })} aria-label="Công đoạn">
            {OperationTypeValues.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
          <select value={row.work_center_id} onChange={(e) => update(index, { work_center_id: e.target.value })} aria-label="Work center">
            <option value="">Work center…</option>
            {centers.data?.items.map((c) => (
              <option key={c.id} value={c.id}>
                {c.code}
              </option>
            ))}
          </select>
        </div>
      ))}
      <div className="actions">
        <button type="button" onClick={() => setRows((r) => [...r, { sequence: '', operation_type: 'QC', work_center_id: '' }])}>
          + Bước
        </button>
        <button type="submit" disabled={save.busy}>
          Lưu các bước
        </button>
      </div>
      <ErrorBox error={save.error} />
    </form>
  )
}

/** POST .../bom/explode only computes (BR-BOM-05); the rounding up is the server's. */
function ExplodePreview({ product }: { product: Product }) {
  const [quantity, setQuantity] = useState('')
  const [result, setResult] = useState<Explosion | null>(null)
  const explode = useSubmit(async (qty: number) => (await api.post<Explosion>(`/products/${product.id}/bom/explode`, { quantity: qty })).data)
  return (
    <section>
      <h2>Xem trước bung BOM</h2>
      <form
        className="row"
        onSubmit={async (e: FormEvent) => {
          e.preventDefault()
          setResult((await explode.submit(Number(quantity))) ?? null)
        }}
      >
        <label>
          Số lượng sản phẩm
          <input value={quantity} onChange={(e) => setQuantity(e.target.value)} inputMode="numeric" required />
        </label>
        <button disabled={explode.busy}>Tính</button>
      </form>
      <ErrorBox error={explode.error} />
      {result && (
        <table>
          <thead>
            <tr>
              <th>Vật tư</th>
              <th>Định mức</th>
              <th>Hao hụt</th>
              <th>Nhu cầu</th>
            </tr>
          </thead>
          <tbody>
            {result.items.map((i) => (
              <tr key={i.material_id}>
                <td>{i.material_code}</td>
                <td>{i.qty_per_unit}</td>
                <td>{i.scrap_rate}</td>
                <td>
                  <strong>{i.required_quantity}</strong> {i.unit}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  )
}
