import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'

import type { Order, Reservation } from '../api/types'
import { AuthContext, type AuthState } from '../auth/useAuth'
import { OrderDetailPage } from './OrderDetailPage'

const client = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), patch: vi.fn() }))
vi.mock('../api/client', () => ({ api: client }))

const order: Order = {
  id: 7,
  order_number: 'PO-2026-00007',
  product_id: 1,
  product_code: 'FRAME-A',
  planned_quantity: 400,
  completed_quantity: null,
  due_date: '2026-10-11T08:00:00Z',
  status: 'DRAFT',
  notes: null,
  bom_header_id: 1,
  routing_id: 1,
  cancel_reason: null,
  created_at: '2026-10-01T08:00:00Z',
  started_at: null,
  completed_at: null,
  allowed_actions: ['plan', 'cancel'],
}

function respond(current: Order) {
  client.get.mockImplementation(async (path: string) => {
    if (path.endsWith('/materials')) return { data: { items: [], total: 0 } }
    if (path.endsWith('/operations'))
      return { data: { items: [], total: 0, workflow_progress: 0, finished_progress: 0 } }
    return { data: current }
  })
}

function renderPage(permissions: string[]) {
  const auth: AuthState = {
    me: null,
    ready: true,
    login: async () => {},
    logout: () => {},
    can: (p) => permissions.includes(p),
  }
  render(
    <AuthContext.Provider value={auth}>
      <MemoryRouter initialEntries={['/orders/7']}>
        <Routes>
          <Route path="/orders/:id" element={<OrderDetailPage />} />
        </Routes>
      </MemoryRouter>
    </AuthContext.Provider>,
  )
}

beforeEach(() => vi.clearAllMocks())

describe('OrderDetailPage', () => {
  it('BR-PO-05: shows exactly the actions the server allows, nothing else', async () => {
    respond(order)
    renderPage(['order:read'])
    expect(await screen.findByRole('button', { name: 'Lập kế hoạch (giữ hàng)' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Hủy lệnh' })).toBeInTheDocument()
    for (const hidden of ['Bắt đầu sản xuất', 'Kiểm tra lại vật tư', 'Sửa lệnh']) {
      expect(screen.queryByRole('button', { name: hidden })).not.toBeInTheDocument()
    }
  })

  it('posts plan with an Idempotency-Key and shows the shortage table the server returns', async () => {
    respond(order)
    const shortage: Reservation = {
      ...order,
      status: 'MATERIAL_SHORTAGE',
      allowed_actions: ['check-materials', 'cancel'],
      reserved: false,
      material_check: [
        { material_id: 1, material_code: 'STEEL-001', unit: 'kg', required: '1040.000', available: '888.000', shortage: '152.000' },
      ],
    }
    client.post.mockResolvedValue({ data: shortage })
    renderPage(['order:read', 'order:plan'])

    await userEvent.click(await screen.findByRole('button', { name: 'Lập kế hoạch (giữ hàng)' }))

    const [path, , config] = client.post.mock.calls[0]
    expect(path).toBe('/production-orders/7/plan')
    expect(config.headers['Idempotency-Key']).toMatch(/^[0-9a-f-]{36}$/)
    const table = await screen.findByRole('status')
    expect(within(table).getByText('STEEL-001')).toBeInTheDocument()
    expect(within(table).getByText('152.000 kg')).toBeInTheDocument()
  })

  it('shows the API error code and message when an action is refused', async () => {
    respond({ ...order, status: 'READY_TO_PRODUCE', allowed_actions: ['start'] })
    client.post.mockRejectedValue(
      Object.assign(new Error('409'), {
        isAxiosError: true,
        response: {
          status: 409,
          data: { error: { code: 'MATERIALS_NOT_ISSUED', message: 'Issue every line first.', details: [], request_id: 'r' } },
        },
      }),
    )
    renderPage(['order:read', 'order:start'])
    await userEvent.click(await screen.findByRole('button', { name: 'Bắt đầu sản xuất' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('MATERIALS_NOT_ISSUED: Issue every line first.')
  })
})
