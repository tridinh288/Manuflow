import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { AuthContext, type AuthState } from '../auth/useAuth'
import { MyWorkCenterPage } from './MyWorkCenterPage'

const client = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }))
vi.mock('../api/client', () => ({ api: client }))

const welding = {
  id: 25,
  sequence: 20,
  operation_type: 'WELDING',
  work_center_id: 3,
  work_center_code: 'WC-WELD',
  status: 'IN_PROGRESS',
  good_quantity: 38,
  rejected_quantity: 2,
  processed_quantity: 40,
  limit: 100,
  progress: 0.4,
  yield_rate: 0.95,
  started_at: null,
  completed_at: null,
}

describe('MyWorkCenterPage', () => {
  it('lists what the server scoped to the worker, with the limit it computed, and reports deltas', async () => {
    client.get.mockImplementation(async (path: string) =>
      path.endsWith('/operations')
        ? { data: { items: [welding], total: 1, workflow_progress: 0.35, finished_progress: 0 } }
        : {
            data: {
              items: [{ id: 4, order_number: 'PO-2026-00004', product_code: 'FRAME-A', planned_quantity: 100, due_date: '2026-10-01T16:00:00Z' }],
              total: 1,
            },
          },
    )
    client.post.mockResolvedValue({ data: {} })
    const auth: AuthState = { me: null, ready: true, login: async () => {}, logout: () => {}, can: (p) => p === 'operation:report' }
    render(
      <AuthContext.Provider value={auth}>
        <MyWorkCenterPage />
      </AuthContext.Provider>,
    )

    expect(client.get).toHaveBeenCalledWith('/production-orders', { params: { status: 'IN_PROGRESS', limit: 200 } })
    expect(await screen.findByText('40 / 100')).toBeInTheDocument()
    // A worker cannot correct, so no reason field (operation:correct is PM only).
    expect(screen.queryByLabelText(/Lý do/)).not.toBeInTheDocument()

    await userEvent.type(screen.getByLabelText('Đạt'), '30')
    await userEvent.type(screen.getByLabelText('Lỗi'), '1')
    await userEvent.click(screen.getByRole('button', { name: 'Báo' }))
    const [path, body, config] = client.post.mock.calls[0]
    expect(path).toBe('/production-operations/25/progress')
    expect(body).toEqual({ good_delta: 30, rejected_delta: 1 })
    expect(config.headers['Idempotency-Key']).toBeTruthy()
  })
})
