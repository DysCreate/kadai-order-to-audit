import { renderToString } from 'react-dom/server'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { describe, expect, it } from 'vitest'
import BenchmarkPage from './BenchmarkPage'
import '../../i18n'

describe('BenchmarkPage', () => {
  it('renders the console heading, run action and rollback note', () => {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } }
    })

    const html = renderToString(
      <QueryClientProvider client={queryClient}>
        <BenchmarkPage />
      </QueryClientProvider>
    )

    expect(html).toContain('Benchmark Console')
    expect(html).toContain('Run benchmark')
    expect(html).toContain('rolled back')
  })
})
