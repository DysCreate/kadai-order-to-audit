import { renderToString } from 'react-dom/server'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { describe, expect, it } from 'vitest'
import ReportsPage from './ReportsPage'
import '../../i18n'

describe('ReportsPage', () => {
  it('renders its heading, date filters and loading state through i18n', () => {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } }
    })

    const html = renderToString(
      <QueryClientProvider client={queryClient}>
        <ReportsPage />
      </QueryClientProvider>
    )

    expect(html).toContain('Reports')
    expect(html).toContain('Pick a report and a date range')
    expect(html).toContain('Reconciliation')
  })
})
