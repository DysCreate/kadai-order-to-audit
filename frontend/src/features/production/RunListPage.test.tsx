import { renderToString } from 'react-dom/server'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import RunListPage from './RunListPage'
import '../../i18n'

const auth = vi.hoisted(() => ({ role: 'production' }))

vi.mock('../auth/AuthContext', () => ({
  useAuth: () => ({
    user: { username: 'u', role: auth.role },
    setUser: () => {},
    loading: false
  })
}))

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } }
  })

  return renderToString(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <RunListPage />
      </MemoryRouter>
    </QueryClientProvider>
  )
}

describe('RunListPage', () => {
  it('renders its heading and loading state through i18n', () => {
    auth.role = 'production'
    const html = renderPage()

    expect(html).toContain('Production runs')
    expect(html).toContain('Loading…')
  })

  it.each(['production', 'admin', 'owner'])(
    'offers the plan-run form to %s',
    (role) => {
      auth.role = role
      expect(renderPage()).toContain('Plan a production run')
    }
  )

  it.each(['salesman', 'accountant'])(
    'hides the plan-run form from %s',
    (role) => {
      auth.role = role
      expect(renderPage()).not.toContain('Plan a production run')
    }
  )
})
