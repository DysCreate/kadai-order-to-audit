import { type ReactNode } from 'react'
import { Navigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { useAuth } from '../features/auth/AuthContext'
import { LoadingPanel, Skeleton } from './Skeleton'

export default function PrivateRoute({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth()
  const { t } = useTranslation()

  if (loading) {
    return (
      <LoadingPanel
        label={t('common.loading')}
        className="flex min-h-screen items-center justify-center bg-gray-100 px-6"
      >
        <div className="w-full max-w-sm rounded-lg border border-gray-200 bg-white p-6 shadow-sm">
          <div className="text-2xl font-bold tracking-tight text-blue-900">Kadai</div>
          <Skeleton className="mt-5 h-4 w-2/3" />
          <Skeleton className="mt-2 h-4 w-full" />
          <Skeleton className="mt-6 h-11 w-full" />
        </div>
      </LoadingPanel>
    )
  }
  if (!user) return <Navigate to="/login" replace />
  return <>{children}</>
}
