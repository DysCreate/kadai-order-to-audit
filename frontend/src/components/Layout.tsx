import { useNavigate, Routes, Route, Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { useAuth } from '../features/auth/AuthContext'
import { logout } from '../features/auth/authApi'
import RunListPage from '../features/production/RunListPage'
import RunDetailPage from '../features/production/RunDetailPage'
import NewOrderPage from '../features/sales/NewOrderPage'
import MyOrdersPage from '../features/sales/MyOrdersPage'
import AdminOrderInboxPage from '../features/sales/AdminOrderInboxPage'
import InvoiceListPage from '../features/sales/InvoiceListPage'
import InvoiceDetailPage from '../features/sales/InvoiceDetailPage'
import PaymentsPage from '../features/payments/PaymentsPage'

const ALL_ROLES = ['salesman', 'admin', 'production', 'accountant', 'owner']

const NAV_ITEMS: { to: string; labelKey: string; roles: string[] }[] = [
  { to: '/', labelKey: 'nav.dashboard', roles: ALL_ROLES },
  { to: '/orders/new', labelKey: 'nav.newOrder', roles: ['salesman', 'admin', 'owner'] },
  { to: '/orders', labelKey: 'nav.myOrders', roles: ['salesman', 'admin', 'owner'] },
  { to: '/admin/orders', labelKey: 'nav.orderInbox', roles: ['admin', 'owner'] },
  { to: '/invoices', labelKey: 'nav.invoices', roles: ['salesman', 'admin', 'accountant', 'owner'] },
  { to: '/payments', labelKey: 'nav.payments', roles: ['admin', 'accountant', 'owner'] },
  { to: '/production', labelKey: 'nav.production', roles: ['production', 'admin', 'owner'] }
]

function Dashboard() {
  const { t } = useTranslation()
  return (
    <div className="p-6">
      <h2 className="text-2xl font-semibold text-gray-800">{t('nav.dashboard')}</h2>
      <p className="mt-2 text-gray-500">{t('nav.welcome')}</p>
    </div>
  )
}

export default function Layout() {
  const { user, setUser } = useAuth()
  const navigate = useNavigate()
  const { t } = useTranslation()

  async function handleLogout() {
    try {
      await logout()
    } finally {
      setUser(null)
      navigate('/login', { replace: true })
    }
  }

  const role = user?.role ?? ''
  const navItems = NAV_ITEMS.filter((item) => item.roles.includes(role))

  return (
    <div className="flex min-h-screen flex-col bg-gray-100 md:h-screen md:flex-row">
      {/* Sidebar */}
      <aside className="w-full flex-shrink-0 bg-blue-900 text-white md:flex md:w-56 md:flex-col">
        <div className="px-6 py-5 text-2xl font-bold tracking-tight border-b border-blue-700">
          Kadai
        </div>
        <nav className="flex flex-1 flex-wrap gap-1 px-4 py-4 md:flex-col md:flex-nowrap md:space-y-1">
          {navItems.map((item) => (
            <Link
              key={item.to}
              to={item.to}
              className="flex min-h-[44px] items-center rounded-md px-3 py-2 text-sm font-medium hover:bg-blue-800 transition-colors"
            >
              {t(item.labelKey)}
            </Link>
          ))}
        </nav>
        <div className="px-4 py-4 border-t border-blue-700">
          <div className="text-xs text-blue-300 mb-2">
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
      <main className="flex-1 overflow-y-auto">
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/orders/new" element={<NewOrderPage />} />
          <Route path="/orders" element={<MyOrdersPage />} />
          <Route path="/admin/orders" element={<AdminOrderInboxPage />} />
          <Route path="/invoices" element={<InvoiceListPage />} />
          <Route path="/invoices/:id" element={<InvoiceDetailPage />} />
          <Route path="/payments" element={<PaymentsPage />} />
          <Route path="/production" element={<RunListPage />} />
          <Route path="/production/runs/:id" element={<RunDetailPage />} />
          <Route path="*" element={<Dashboard />} />
        </Routes>
      </main>
    </div>
  )
}
