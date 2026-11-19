import { Routes, Route } from 'react-router-dom'
import LoginPage from './features/auth/LoginPage'
import PrivateRoute from './components/PrivateRoute'
import Layout from './components/Layout'
import { AuthProvider } from './features/auth/AuthContext'

export default function App() {
  return (
    <AuthProvider>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route
          path="/*"
          element={
            <PrivateRoute>
              <Layout />
            </PrivateRoute>
          }
        />
      </Routes>
    </AuthProvider>
  )
}
