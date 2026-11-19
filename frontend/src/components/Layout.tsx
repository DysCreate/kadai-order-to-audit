import { useNavigate, Routes, Route, Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { useAuth } from '../features/auth/AuthContext'
import { logout } from '../features/auth/authApi'

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

  return (
    <div className="flex h-screen bg-gray-100">
      {/* Sidebar */}
      <aside className="w-56 flex-shrink-0 bg-blue-900 text-white flex flex-col">
        <div className="px-6 py-5 text-2xl font-bold tracking-tight border-b border-blue-700">
          Kadai
        </div>
        <nav className="flex-1 px-4 py-4 space-y-1">
          <Link
            to="/"
            className="flex items-center px-3 py-2 rounded-md text-sm font-medium hover:bg-blue-800 transition-colors min-h-[44px]"
          >
            {t('nav.dashboard')}
          </Link>
        </nav>
        <div className="px-4 py-4 border-t border-blue-700">
          <div className="text-xs text-blue-300 mb-2">
            {user?.username} &middot; {user?.role}
          </div>
          <button
            onClick={handleLogout}
            className="w-full text-left px-3 py-2 rounded-md text-sm font-medium text-blue-200 hover:bg-blue-800 hover:text-white transition-colors min-h-[44px]"
          >
            {t('nav.logout')}
          </button>
        </div>
      </aside>

      {/* Main content */}
      <main className="flex-1 overflow-y-auto">
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="*" element={<Dashboard />} />
        </Routes>
      </main>
    </div>
  )
}
