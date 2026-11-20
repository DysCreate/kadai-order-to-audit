import { renderToString } from 'react-dom/server'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import RunListPage from './RunListPage'
import '../../i18n'

describe('RunListPage', () => {
  it('renders its heading and loading state through i18n', () => {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } }
    })

    const html = renderToString(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <RunListPage />
        </MemoryRouter>
      </QueryClientProvider>
    )

    expect(html).toContain('Production runs')
    expect(html).toContain('Loading…')
  })
})
