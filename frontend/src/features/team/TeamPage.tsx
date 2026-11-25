import { useState, type FormEvent } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { apiErrorMessage } from '../../lib/apiError'
import { SkeletonText } from '../../components/Skeleton'
import { useAuth } from '../auth/AuthContext'
import { getTeam, inviteMember } from './teamApi'

export default function TeamPage() {
  const { t } = useTranslation()
  const { user } = useAuth()
  const queryClient = useQueryClient()

  const [email, setEmail] = useState('')
  const [role, setRole] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [sentTo, setSentTo] = useState<string | null>(null)

  const team = useQuery({ queryKey: ['team'], queryFn: getTeam })
  const invitableRoles = team.data?.invitable_roles ?? []
  const selectedRole = invitableRoles.includes(role) ? role : (invitableRoles[0] ?? '')

  const mutation = useMutation({
    mutationFn: () => inviteMember({ email, role: selectedRole }),
    onSuccess: (invitation) => {
      setError(null)
      setSentTo(invitation.email)
      setEmail('')
      queryClient.invalidateQueries({ queryKey: ['team'] })
    },
    onError: (failure) => {
      setSentTo(null)
      setError(apiErrorMessage(failure, t('team.inviteError')))
    }
  })

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError(null)
    setSentTo(null)
    if (selectedRole === '') {
      setError(t('team.noInviteRoles'))
      return
    }
    mutation.mutate()
  }

  return (
    <div className="mx-auto max-w-4xl p-4 sm:p-6">
      <h2 className="text-2xl font-semibold text-gray-800">{t('team.title')}</h2>
      <p className="mt-1 text-sm text-gray-500">
        {user?.role === 'owner' ? t('team.ownerSubtitle') : t('team.adminSubtitle')}
      </p>

      {error && (
        <div role="alert" className="mt-4 rounded-md border border-red-300 bg-red-50 p-3 text-sm text-red-700">
          {error}
        </div>
      )}
      {sentTo && (
        <div role="status" className="mt-4 rounded-md border border-green-300 bg-green-50 p-3 text-sm text-green-800">
          {t('team.inviteSent', { email: sentTo })}
        </div>
      )}

      <form className="mt-6 space-y-3 rounded-lg border border-gray-200 bg-white p-4" onSubmit={handleSubmit}>
        <h3 className="text-lg font-semibold text-gray-800">{t('team.inviteTitle')}</h3>
        <p className="text-sm text-gray-500">
          {user?.role === 'owner' ? t('team.ownerInviteHint') : t('team.adminInviteHint')}
        </p>

        {team.isLoading && <SkeletonText lines={2} />}
        {team.isError && (
          <p className="text-sm text-red-700">{t('team.loadError')}</p>
        )}

        {!team.isLoading && !team.isError && (
          <div className="grid gap-3 sm:grid-cols-[1fr_14rem_auto] sm:items-end">
            <div>
              <label htmlFor="invite-email" className="block text-sm font-medium text-gray-700">
                {t('team.email')}
              </label>
              <input
                id="invite-email"
                type="email"
                required
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                className="mt-1 block min-h-[44px] w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500"
              />
            </div>
            <div>
              <label htmlFor="invite-role" className="block text-sm font-medium text-gray-700">
                {t('team.role')}
              </label>
              <select
                id="invite-role"
                value={selectedRole}
                onChange={(event) => setRole(event.target.value)}
                className="mt-1 block min-h-[44px] w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500"
              >
                {invitableRoles.map((value) => (
                  <option key={value} value={value}>
                    {t(`roles.${value}`)}
                  </option>
                ))}
              </select>
            </div>
            <button
              type="submit"
              disabled={mutation.isPending || invitableRoles.length === 0 || email.trim() === ''}
              className="min-h-[44px] rounded-md bg-blue-800 px-4 py-2 font-semibold text-white hover:bg-blue-700 disabled:opacity-50"
            >
              {mutation.isPending ? '…' : t('team.sendInvite')}
            </button>
          </div>
        )}
      </form>

      <section className="mt-6">
        <h3 className="text-lg font-semibold text-gray-800">{t('team.members')}</h3>
        <div className="mt-2 overflow-x-auto rounded-lg border border-gray-200 bg-white">
          <table className="min-w-full divide-y divide-gray-200 text-sm">
            <thead className="bg-gray-50">
              <tr>
                <th className="px-3 py-2 text-left font-semibold text-gray-600">{t('team.username')}</th>
                <th className="px-3 py-2 text-left font-semibold text-gray-600">{t('team.email')}</th>
                <th className="px-3 py-2 text-left font-semibold text-gray-600">{t('team.role')}</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {team.isLoading && (
                <tr>
                  <td colSpan={3} className="px-3 py-4">
                    <SkeletonText lines={3} />
                  </td>
                </tr>
              )}
              {!team.isLoading &&
                (team.data?.members ?? []).map((member) => (
                  <tr key={member.id}>
                    <td className="px-3 py-2 font-medium text-gray-900">{member.username}</td>
                    <td className="px-3 py-2 text-gray-700">{member.email || '—'}</td>
                    <td className="px-3 py-2 text-gray-700">{t(`roles.${member.role}`)}</td>
                  </tr>
                ))}
            </tbody>
          </table>
        </div>
      </section>

      {(team.data?.invitations ?? []).length > 0 && (
        <section className="mt-6">
          <h3 className="text-lg font-semibold text-gray-800">{t('team.pending')}</h3>
          <ul className="mt-2 divide-y divide-gray-100 rounded-lg border border-gray-200 bg-white">
            {(team.data?.invitations ?? []).map((invitation) => (
              <li key={invitation.id} className="flex flex-wrap items-center justify-between gap-2 px-4 py-3 text-sm">
                <span className="font-medium text-gray-900">{invitation.email}</span>
                <span className="text-gray-600">{t(`roles.${invitation.role}`)}</span>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  )
}
