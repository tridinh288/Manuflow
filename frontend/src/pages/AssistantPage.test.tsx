import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { AssistantPage } from './AssistantPage'

const client = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }))
vi.mock('../api/client', () => ({ api: client, idem: (key: string) => ({ headers: { 'Idempotency-Key': key } }) }))

beforeEach(() => vi.clearAllMocks())

describe('AssistantPage', () => {
  it('says so when the server has no assistant configured', async () => {
    client.get.mockResolvedValue({ data: { enabled: false, provider: 'anthropic', model: null, tools: [] } })
    render(<AssistantPage />)
    expect(await screen.findByText(/chưa được bật/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Hỏi' })).not.toBeInTheDocument()
  })

  it('BR-AI-03: shows the answer, the tools used, and warns about ungrounded numbers', async () => {
    client.get.mockResolvedValue({
      data: { enabled: true, provider: 'anthropic', model: 'm', tools: ['check_material_availability'] },
    })
    client.post.mockResolvedValue({
      data: {
        answer: 'Thiếu 152.000 kg STEEL-001, khoảng 5 ngày nữa.',
        grounded: false,
        ungrounded_numbers: ['5'],
        tool_calls: [
          { name: 'check_material_availability', arguments: { product_code: 'FRAME-A', quantity: 400 }, ok: true, result: {} },
        ],
      },
    })
    render(<AssistantPage />)
    await userEvent.type(await screen.findByLabelText('Câu hỏi'), 'Làm 400 FRAME-A được không?')
    await userEvent.click(screen.getByRole('button', { name: 'Hỏi' }))

    expect(client.post).toHaveBeenCalledWith(
      '/assistant/ask',
      { question: 'Làm 400 FRAME-A được không?' },
      expect.objectContaining({ headers: expect.any(Object) }),
    )
    expect(await screen.findByText('Thiếu 152.000 kg STEEL-001, khoảng 5 ngày nữa.')).toBeInTheDocument()
    expect(screen.getByRole('status')).toHaveTextContent('số không có trong dữ liệu tra cứu: 5')
    expect(screen.getByText('check_material_availability')).toBeInTheDocument()
  })
})
