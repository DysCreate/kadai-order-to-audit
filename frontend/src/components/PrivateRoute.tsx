import { type ReactNode } from 'react'
import { Navigate } from 'react-router-dom'
import { useAuth } from '../features/auth/AuthContext'

export default function PrivateRoute({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth()
  if (loading) {
    return (
      <div className="flex items-center justify-center h-screen text-gray-500">
        Loading…
      </div>
    )
  }
  if (!user) return <Navigate to="/login" replace />
  return <>{children}</>
}
