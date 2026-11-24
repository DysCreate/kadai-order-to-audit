import { renderToString } from 'react-dom/server'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import Layout, { landingForRole } from './Layout'
import '../i18n'

const auth = vi.hoisted(() => ({ role: 'production' }))

vi.mock('../features/auth/AuthContext', () => ({
  useAuth: () => ({
    user: { username: 'u', role: auth.role },
    setUser: () => {},
    loading: false
  })
}))

function renderLayout(path: string) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } }
  })

  return renderToString(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[path]}>
        <Layout />
      </MemoryRouter>
    </QueryClientProvider>
  )
}

describe('Layout', () => {
  beforeEach(() => {
    auth.role = 'production'
  })

  it('lands each role on its own home screen', () => {
    expect(landingForRole('production')).toBe('production')
    expect(landingForRole('salesman')).toBe('salesman')
    expect(landingForRole('admin')).toBe('dashboard')
    expect(landingForRole('accountant')).toBe('dashboard')
    expect(landingForRole('owner')).toBe('dashboard')
  })

  it('keeps the dashboard link out of the production navigation', () => {
    const html = renderLayout('/production')

    expect(html).toContain('>Production<')
    expect(html).toContain('>Reports<')
    expect(html).not.toContain('>Dashboard<')
  })

  it('keeps the dashboard link for admin', () => {
    auth.role = 'admin'
    const html = renderLayout('/production')

    expect(html).toContain('>Dashboard<')
  })
})
