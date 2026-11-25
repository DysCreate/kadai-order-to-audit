import { useNavigate, Navigate, Routes, Route, NavLink } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import LanguageToggle from './LanguageToggle'
import { useAuth } from '../features/auth/AuthContext'
import { logout } from '../features/auth/authApi'
import { useOnline, useOutbox } from '../features/sales/offline/useOutbox'
import RunListPage from '../features/production/RunListPage'
import RunDetailPage from '../features/production/RunDetailPage'
import NewOrderPage from '../features/sales/NewOrderPage'
import MyOrdersPage from '../features/sales/MyOrdersPage'
import AdminOrderInboxPage from '../features/sales/AdminOrderInboxPage'
import InvoiceListPage from '../features/sales/InvoiceListPage'
import InvoiceDetailPage from '../features/sales/InvoiceDetailPage'
import PaymentsPage from '../features/payments/PaymentsPage'
import DashboardPage from '../features/dashboard/DashboardPage'
import SalesmanDashboardPage from '../features/dashboard/SalesmanDashboardPage'
import ReportsPage from '../features/reports/ReportsPage'
import TeamPage from '../features/team/TeamPage'
import NotFoundPage from './NotFoundPage'

const NAV_ITEMS: { to: string; labelKey: string; roles: string[] }[] = [
  // Production has no dashboard access on the server (PS 12), so it lands on
  // the run list instead of a screen that can only show an error.
  { to: '/', labelKey: 'nav.dashboard', roles: ['salesman', 'admin', 'accountant', 'owner'] },
  { to: '/orders/new', labelKey: 'nav.newOrder', roles: ['salesman', 'admin', 'owner'] },
  { to: '/orders', labelKey: 'nav.myOrders', roles: ['salesman', 'admin', 'owner'] },
  { to: '/admin/orders', labelKey: 'nav.orderInbox', roles: ['admin', 'owner'] },
  { to: '/invoices', labelKey: 'nav.invoices', roles: ['salesman', 'admin', 'accountant', 'owner'] },
  { to: '/payments', labelKey: 'nav.payments', roles: ['admin', 'accountant', 'owner'] },
  { to: '/production', labelKey: 'nav.production', roles: ['production', 'admin', 'owner'] },
  { to: '/reports', labelKey: 'nav.reports', roles: ['admin', 'production', 'accountant', 'owner'] },
  { to: '/team', labelKey: 'nav.team', roles: ['admin', 'owner'] }
]

export type Landing = 'salesman' | 'production' | 'dashboard'

/**
 * Which screen a role sees at `/`.
 *
 * A salesman gets a dashboard scoped to their own orders (the server denies
 * them the all-salesman report dashboard), and production has no dashboard
 * access on the server (PS 12), so it lands on the run list instead.
 */
export function landingForRole(role: string): Landing {
  if (role === 'salesman') return 'salesman'
  if (role === 'production') return 'production'
  return 'dashboard'
}

export default function Layout() {
  const { user, setUser } = useAuth()
  const navigate = useNavigate()
  const { t } = useTranslation()
  const online = useOnline()
  const { pending, syncing, error: syncError, sync } = useOutbox(user?.username)

  async function handleLogout() {
    try {
      await logout()
    } finally {
      setUser(null)
      navigate('/login', { replace: true })
    }
  }

  const role = user?.role ?? ''
  const landing = landingForRole(role)
  const navItems = NAV_ITEMS.filter((item) => item.roles.includes(role))

  return (
    <div className="flex min-h-screen flex-col bg-gray-100 md:h-screen md:flex-row">
      <a
        href="#main-content"
        className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50 focus:rounded-md focus:bg-white focus:px-4 focus:py-2 focus:text-sm focus:font-semibold focus:text-blue-900 focus:shadow-lg"
      >
        {t('nav.skipToContent')}
      </a>
      {/* Sidebar */}
      <aside className="w-full flex-shrink-0 bg-blue-900 text-white md:flex md:w-56 md:flex-col">
        <div className="flex items-center justify-between border-b border-blue-700 px-6 py-5">
          <div className="text-2xl font-bold tracking-tight">Kadai</div>
          <LanguageToggle className="md:hidden" />
        </div>
        <nav
          aria-label={t('nav.primary')}
          className="flex flex-1 flex-wrap gap-1 px-4 py-4 md:flex-col md:flex-nowrap md:space-y-1"
        >
          {navItems.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.to === '/' || item.to === '/orders'}
              className={({ isActive }) =>
                `flex min-h-[44px] items-center rounded-md px-3 py-2 text-sm font-medium transition-colors ${
                  isActive ? 'bg-blue-800 text-white' : 'hover:bg-blue-800'
                }`
              }
            >
              {t(item.labelKey)}
            </NavLink>
          ))}
        </nav>
        <div className="px-4 py-4 border-t border-blue-700">
          {!online && (
            <p className="mb-2 rounded bg-amber-500/20 px-2 py-1 text-xs text-amber-100">
              {t('offline.banner')}
            </p>
          )}
          {(pending > 0 || syncing) && (
            <div className="mb-2 flex items-center justify-between gap-2 rounded bg-blue-800 px-2 py-2 text-xs">
              <span>{syncing ? t('offline.syncing') : t('offline.pending', { count: pending })}</span>
              <button
                type="button"
                onClick={() => void sync()}
                disabled={syncing || !online}
                className="rounded bg-white px-2 py-1 font-semibold text-blue-900 disabled:opacity-50"
              >
                {t('offline.syncNow')}
              </button>
            </div>
          )}
          {syncError && (
            <p role="alert" className="mb-2 text-xs text-red-200">
              {t('offline.syncFailed')}
            </p>
          )}
          <div className="text-xs text-blue-300 mb-2">
            {user?.organization?.name && <div>{user.organization.name}</div>}
            {user?.username} &middot; {user?.role}
          </div>
          <button
            onClick={handleLogout}
            className="w-full min-h-[44px] rounded-md px-3 py-2 text-left text-sm font-medium text-blue-200 hover:bg-blue-800 hover:text-white transition-colors"
          >
            {t('nav.logout')}
          </button>
        </div>
      </aside>

      {/* Main content */}
      <div className="flex min-h-0 flex-1 flex-col">
        <header className="hidden flex-shrink-0 items-center justify-end border-b border-gray-200 bg-white px-4 py-2 md:flex">
          <LanguageToggle />
        </header>
        <main id="main-content" tabIndex={-1} className="flex-1 overflow-y-auto focus:outline-none">
          <Routes>
            <Route
              path="/"
              element={
                landing === 'salesman' ? (
                  <SalesmanDashboardPage />
                ) : landing === 'production' ? (
                  <Navigate to="/production" replace />
                ) : (
                  <DashboardPage />
                )
              }
            />
            <Route path="/orders/new" element={<NewOrderPage />} />
            <Route path="/orders" element={<MyOrdersPage />} />
            <Route path="/admin/orders" element={<AdminOrderInboxPage />} />
            <Route path="/invoices" element={<InvoiceListPage />} />
            <Route path="/invoices/:id" element={<InvoiceDetailPage />} />
            <Route path="/payments" element={<PaymentsPage />} />
            <Route path="/production" element={<RunListPage />} />
            <Route path="/production/runs/:id" element={<RunDetailPage />} />
            <Route path="/reports" element={<ReportsPage />} />
            <Route path="/team" element={<TeamPage />} />
            <Route path="*" element={<NotFoundPage />} />
          </Routes>
        </main>
      </div>
    </div>
  )
}
