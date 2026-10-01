import type { Me } from '../api/types'
import { visibleMenu } from './menu'

function user(role: Me['role'], permissions: string[], workCenter: number | null = null): Me {
  return { id: 1, username: 'u', full_name: 'U', role, work_center_id: workCenter, permissions }
}

describe('B17: the menu comes from the permissions in /auth/me', () => {
  it('shows the dashboard only with dashboard:read', () => {
    expect(visibleMenu(user('PRODUCTION_MANAGER', ['dashboard:read'])).map((i) => i.to)).toContain(
      '/dashboard',
    )
    expect(visibleMenu(user('WORKER', ['order:read'])).map((i) => i.to)).not.toContain('/dashboard')
  })

  it('shows nothing for a user without permissions', () => {
    expect(visibleMenu(user('WORKER', []))).toEqual([])
  })
})
