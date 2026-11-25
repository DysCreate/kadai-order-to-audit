import { useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { apiErrorMessage } from '../../lib/apiError'
import { registerOrganization } from './authApi'
import { useAuth } from './AuthContext'

export default function RegisterPage() {
  const { t } = useTranslation()
  const { setUser } = useAuth()
  const navigate = useNavigate()

  const [organizationName, setOrganizationName] = useState('')
  const [username, setUsername] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError(null)
    if (password !== confirmPassword) {
      setError(t('register.passwordMismatch'))
      return
    }

    setSubmitting(true)
    try {
      const user = await registerOrganization({
        organization_name: organizationName,
        username,
        email,
        password
      })
      setUser(user)
      navigate('/', { replace: true })
    } catch (failure) {
      setError(apiErrorMessage(failure, t('register.error')))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-gray-50 px-4 py-10">
      <div className="w-full max-w-md space-y-6">
        <div>
          <h1 className="text-center text-3xl font-bold text-blue-800">Kadai</h1>
          <h2 className="mt-2 text-center text-xl text-gray-700">{t('register.title')}</h2>
          <p className="mt-1 text-center text-sm text-gray-500">{t('register.subtitle')}</p>
        </div>

        <form className="space-y-4 rounded-lg border border-gray-200 bg-white p-6 shadow-sm" onSubmit={handleSubmit}>
          {error && (
            <div role="alert" className="rounded-md border border-red-300 bg-red-50 p-3 text-sm text-red-700">
              {error}
            </div>
          )}

          <div>
            <label htmlFor="organization-name" className="block text-sm font-medium text-gray-700">
              {t('register.organization')}
            </label>
            <input
              id="organization-name"
              type="text"
              required
              autoComplete="organization"
              value={organizationName}
              onChange={(event) => setOrganizationName(event.target.value)}
              className="mt-1 block min-h-[44px] w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500"
            />
          </div>

          <div>
            <label htmlFor="register-username" className="block text-sm font-medium text-gray-700">
              {t('register.username')}
            </label>
            <input
              id="register-username"
              type="text"
              required
              autoComplete="username"
              value={username}
              onChange={(event) => setUsername(event.target.value)}
              className="mt-1 block min-h-[44px] w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500"
            />
          </div>

          <div>
            <label htmlFor="register-email" className="block text-sm font-medium text-gray-700">
              {t('register.email')}
            </label>
            <input
              id="register-email"
              type="email"
              required
              autoComplete="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              className="mt-1 block min-h-[44px] w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500"
            />
          </div>

          <div>
            <label htmlFor="register-password" className="block text-sm font-medium text-gray-700">
              {t('register.password')}
            </label>
            <input
              id="register-password"
              type="password"
              required
              autoComplete="new-password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              className="mt-1 block min-h-[44px] w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500"
            />
          </div>

          <div>
            <label htmlFor="register-confirm" className="block text-sm font-medium text-gray-700">
              {t('register.confirmPassword')}
            </label>
            <input
              id="register-confirm"
              type="password"
              required
              autoComplete="new-password"
              value={confirmPassword}
              onChange={(event) => setConfirmPassword(event.target.value)}
              className="mt-1 block min-h-[44px] w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500"
            />
          </div>

          <button
            type="submit"
            disabled={submitting}
            className="flex min-h-[44px] w-full justify-center rounded-md bg-blue-800 px-4 py-3 text-sm font-semibold text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {submitting ? '…' : t('register.submit')}
          </button>
        </form>

        <p className="text-center text-sm text-gray-600">
          {t('register.haveAccount')}{' '}
          <Link to="/login" className="font-medium text-blue-800 hover:underline">
            {t('register.signIn')}
          </Link>
        </p>
      </div>
    </div>
  )
}
