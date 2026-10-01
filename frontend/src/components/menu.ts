import type { Me } from '../api/types'

export type MenuItem = { to: string; label: string; visible: (me: Me) => boolean }

const has = (permission: string) => (me: Me) => me.permissions.includes(permission)

/** Visibility comes only from /auth/me; the server still checks every request (B4). */
export const MENU: MenuItem[] = [
  { to: '/dashboard', label: 'Dashboard', visible: has('dashboard:read') },
]

export function visibleMenu(me: Me): MenuItem[] {
  return MENU.filter((item) => item.visible(me))
}
