import { useState, type FormEvent } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { apiErrorMessage } from '../../lib/apiError'
import { LoadingPanel, SkeletonText } from '../../components/Skeleton'
import { acceptInvitation, getInvitation } from './authApi'
import { useAuth } from './AuthContext'

export default function AcceptInvitePage() {
  const { token = '' } = useParams()
  const { t } = useTranslation()
  const { setUser } = useAuth()
  const navigate = useNavigate()

  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  const invitation = useQuery({
    queryKey: ['invitation', token],
    queryFn: () => getInvitation(token),
    enabled: token !== '',
    retry: false
  })

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError(null)
    if (password !== confirmPassword) {
      setError(t('invite.passwordMismatch'))
      return
    }

    setSubmitting(true)
    try {
      const user = await acceptInvitation(token, { username, password })
      setUser(user)
      navigate('/', { replace: true })
    } catch (failure) {
      setError(apiErrorMessage(failure, t('invite.error')))
    } finally {
      setSubmitting(false)
    }
  }

  if (invitation.isLoading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-gray-50 px-4">
        <LoadingPanel label={t('common.loading')}>
          <div className="w-full max-w-sm rounded-lg border border-gray-200 bg-white p-6 shadow-sm">
            <SkeletonText lines={4} />
          </div>
        </LoadingPanel>
      </div>
    )
  }

  if (invitation.isError || !invitation.data) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-gray-50 px-4">
        <div className="w-full max-w-sm rounded-lg border border-red-200 bg-white p-6 text-center shadow-sm">
          <h1 className="text-xl font-semibold text-gray-900">{t('invite.invalidTitle')}</h1>
          <p className="mt-2 text-sm text-gray-600">{t('invite.invalid')}</p>
          <Link to="/login" className="mt-4 inline-block font-medium text-blue-800 hover:underline">
            {t('invite.backToSignIn')}
          </Link>
        </div>
      </div>
    )
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-gray-50 px-4 py-10">
      <div className="w-full max-w-md space-y-6">
        <div>
          <h1 className="text-center text-3xl font-bold text-blue-800">Kadai</h1>
          <h2 className="mt-2 text-center text-xl text-gray-700">{t('invite.title')}</h2>
          <p className="mt-1 text-center text-sm text-gray-500">
            {t('invite.subtitle', {
              organization: invitation.data.organization_name,
              role: t(`roles.${invitation.data.role}`)
            })}
          </p>
        </div>

        <form className="space-y-4 rounded-lg border border-gray-200 bg-white p-6 shadow-sm" onSubmit={handleSubmit}>
          {error && (
            <div role="alert" className="rounded-md border border-red-300 bg-red-50 p-3 text-sm text-red-700">
              {error}
            </div>
          )}

          <div>
            <label htmlFor="invite-email" className="block text-sm font-medium text-gray-700">
              {t('invite.email')}
            </label>
            <input
              id="invite-email"
              type="email"
              readOnly
              value={invitation.data.email}
              className="mt-1 block min-h-[44px] w-full rounded-md border-gray-200 bg-gray-50 text-gray-600 shadow-sm"
            />
          </div>

          <div>
            <label htmlFor="invite-username" className="block text-sm font-medium text-gray-700">
              {t('invite.username')}
            </label>
            <input
              id="invite-username"
              type="text"
              required
              autoComplete="username"
              value={username}
              onChange={(event) => setUsername(event.target.value)}
              className="mt-1 block min-h-[44px] w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500"
            />
          </div>

          <div>
            <label htmlFor="invite-password" className="block text-sm font-medium text-gray-700">
              {t('invite.password')}
            </label>
            <input
              id="invite-password"
              type="password"
              required
              autoComplete="new-password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              className="mt-1 block min-h-[44px] w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500"
            />
          </div>

          <div>
            <label htmlFor="invite-confirm" className="block text-sm font-medium text-gray-700">
              {t('invite.confirmPassword')}
            </label>
            <input
              id="invite-confirm"
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
            {submitting ? '…' : t('invite.submit')}
          </button>
        </form>
      </div>
    </div>
  )
}
