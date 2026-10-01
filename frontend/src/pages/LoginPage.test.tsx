import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { AxiosError, AxiosHeaders } from 'axios'
import { MemoryRouter } from 'react-router-dom'

import { AuthContext, type AuthState } from '../auth/useAuth'
import { LoginPage } from './LoginPage'

function renderWith(login: AuthState['login']) {
  const value: AuthState = { me: null, ready: true, login, logout: () => {}, can: () => false }
  render(
    <AuthContext.Provider value={value}>
      <MemoryRouter>
        <LoginPage />
      </MemoryRouter>
    </AuthContext.Provider>,
  )
}

describe('LoginPage', () => {
  it('shows the generic message the API returns (BR-AUTH-05), nothing more', async () => {
    const config = { headers: new AxiosHeaders() }
    const failure = new AxiosError('401', '401', config, null, {
      status: 401,
      statusText: '',
      headers: {},
      config,
      data: {
        error: {
          code: 'INVALID_CREDENTIALS',
          message: 'Invalid username or password.',
          details: [],
          request_id: 'r',
        },
      },
    })
    const login = vi.fn().mockRejectedValue(failure)
    renderWith(login)

    await userEvent.type(screen.getByLabelText('Tên đăng nhập'), 'demo.manager')
    await userEvent.type(screen.getByLabelText('Mật khẩu'), 'wrong-password')
    await userEvent.click(screen.getByRole('button', { name: 'Đăng nhập' }))

    expect(login).toHaveBeenCalledWith('demo.manager', 'wrong-password')
    expect(await screen.findByRole('alert')).toHaveTextContent('Invalid username or password.')
  })
})
