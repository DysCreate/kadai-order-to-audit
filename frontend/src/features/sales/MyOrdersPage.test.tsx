import { renderToString } from 'react-dom/server'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import MyOrdersPage from './MyOrdersPage'
import '../../i18n'

describe('MyOrdersPage', () => {
  it('renders its heading and loading state through i18n', () => {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } }
    })

    const html = renderToString(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <MyOrdersPage />
        </MemoryRouter>
      </QueryClientProvider>
    )

    expect(html).toContain('My orders')
    expect(html).toContain('Loading…')
  })
})
