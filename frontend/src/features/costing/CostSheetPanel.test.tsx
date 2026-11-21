import { renderToString } from 'react-dom/server'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { describe, expect, it } from 'vitest'
import CostSheetPanel from './CostSheetPanel'
import '../../i18n'

describe('CostSheetPanel', () => {
  it('renders its loading state through i18n', () => {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } }
    })

    const html = renderToString(
      <QueryClientProvider client={queryClient}>
        <CostSheetPanel runId={1} />
      </QueryClientProvider>
    )

    expect(html).toContain('Loading cost sheet…')
  })
})
