import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { AuthContext, type AuthState } from '../auth/useAuth'
import { AuditPage } from './AuditPage'
import { InventoryPage } from './InventoryPage'

const client = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }))
vi.mock('../api/client', () => ({ api: client, idem: (key: string) => ({ headers: { 'Idempotency-Key': key } }) }))

function auth(permissions: string[]): AuthState {
  return { me: null, ready: true, login: async () => {}, logout: () => {}, can: (p) => permissions.includes(p) }
}

const steel = {
  material_id: 1,
  material_code: 'STEEL-001',
  material_name: 'Steel sheet',
  unit: 'kg',
  active: true,
  on_hand_quantity: '1040.000',
  reserved_quantity: '152.000',
  available_quantity: '888.000',
  minimum_stock: '1000.000',
  low_stock: true,
  below_minimum_by: '112.000',
}

beforeEach(() => vi.clearAllMocks())

describe('InventoryPage', () => {
  it('receives stock with an Idempotency-Key and shows the balance the server returns', async () => {
    client.get.mockResolvedValue({ data: { items: [steel], total: 1 } })
    client.post.mockResolvedValue({
      data: { type: 'RECEIVE', material_code: 'STEEL-001', unit: 'kg', on_hand_delta: '200.000', on_hand_quantity: '1240.000', available_quantity: '1088.000' },
    })
    render(
      <AuthContext.Provider value={auth(['inventory:read', 'inventory:receive'])}>
        <InventoryPage />
      </AuthContext.Provider>,
    )
    const form = (await screen.findByRole('heading', { name: 'Nhập kho / điều chỉnh' })).closest('section')!
    await userEvent.selectOptions(within(form).getByRole('combobox', { name: /Vật tư/ }), '1')
    await userEvent.type(within(form).getByLabelText(/^Số lượng/), '200')
    await userEvent.click(within(form).getByRole('button', { name: 'Nhập kho' }))

    const [path, body, config] = client.post.mock.calls[0]
    expect(path).toBe('/inventory/receipts')
    expect(body).toEqual({ material_id: 1, quantity: '200' })
    expect(config.headers['Idempotency-Key']).toBeTruthy()
    expect(await screen.findByRole('status')).toHaveTextContent('tồn 1240.000, khả dụng 1088.000')
    // Without inventory:adjust there is no adjustment button (B4).
    expect(screen.queryByRole('button', { name: 'Điều chỉnh' })).not.toBeInTheDocument()
  })
})

describe('AuditPage', () => {
  it('BR-AUD-06: filters on the server, with timezone-aware dates (D-23)', async () => {
    client.get.mockResolvedValue({ data: { items: [], total: 0 } })
    render(
      <AuthContext.Provider value={auth(['audit:read'])}>
        <AuditPage />
      </AuthContext.Provider>,
    )
    await userEvent.selectOptions(screen.getByLabelText('Hành động'), 'ORDER_COMPLETED')
    await userEvent.type(screen.getByLabelText('Từ'), '2026-10-01T08:00')

    const params = client.get.mock.calls.at(-1)?.[1].params
    expect(client.get.mock.calls.at(-1)?.[0]).toBe('/audit-logs')
    expect(params.action).toBe('ORDER_COMPLETED')
    expect(params.created_from).toMatch(/Z$/)
    expect(params.offset).toBe(0)
  })
})
