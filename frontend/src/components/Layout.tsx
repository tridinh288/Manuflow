import { NavLink, Outlet } from 'react-router-dom'

import { useAuth } from '../auth/useAuth'
import { visibleMenu } from './menu'

export function Layout() {
  const { me, logout } = useAuth()
  if (me === null) return null
  return (
    <div className="shell">
      <header className="topbar">
        <strong>Manuflow</strong>
        <nav aria-label="Chính">
          {visibleMenu(me).map((item) => (
            <NavLink key={item.to} to={item.to}>
              {item.label}
            </NavLink>
          ))}
        </nav>
        <span className="who">
          {me.full_name} · {me.role}
          <button type="button" className="link" onClick={logout}>
            Đăng xuất
          </button>
        </span>
      </header>
      <main>
        <Outlet />
      </main>
    </div>
  )
}
