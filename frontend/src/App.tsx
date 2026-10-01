import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import type { ReactNode } from 'react'

import { AuthProvider } from './auth/AuthContext'
import { useAuth } from './auth/useAuth'
import { Layout } from './components/Layout'
import { visibleMenu } from './components/menu'
import { DashboardPage } from './pages/DashboardPage'
import { LoginPage } from './pages/LoginPage'
import { MyWorkCenterPage } from './pages/MyWorkCenterPage'
import { OrderDetailPage } from './pages/OrderDetailPage'
import { OrdersPage } from './pages/OrdersPage'

function RequireLogin({ children }: { children: ReactNode }) {
  const { me, ready } = useAuth()
  if (!ready) return <p className="muted">Đang tải…</p>
  return me === null ? <Navigate to="/login" replace /> : children
}

function Home() {
  const { me } = useAuth()
  const first = me ? visibleMenu(me)[0] : undefined
  return first ? <Navigate to={first.to} replace /> : <p>Tài khoản này chưa có trang nào.</p>
}

export function AppRoutes() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route
        element={
          <RequireLogin>
            <Layout />
          </RequireLogin>
        }
      >
        <Route index element={<Home />} />
        <Route path="dashboard" element={<DashboardPage />} />
        <Route path="orders" element={<OrdersPage />} />
        <Route path="orders/:id" element={<OrderDetailPage />} />
        <Route path="my-work" element={<MyWorkCenterPage />} />
        <Route path="*" element={<p>Không tìm thấy trang.</p>} />
      </Route>
    </Routes>
  )
}

export default function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <AppRoutes />
      </BrowserRouter>
    </AuthProvider>
  )
}
