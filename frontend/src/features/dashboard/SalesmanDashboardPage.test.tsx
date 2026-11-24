import { renderToString } from 'react-dom/server'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import SalesmanDashboardPage from './SalesmanDashboardPage'
import type { Invoice, Order } from '../sales/salesApi'
import '../../i18n'

vi.mock('../sales/salesApi', () => ({
  listOrders: vi.fn(),
  listInvoices: vi.fn(),
  getSalesSummary: vi.fn()
}))

function renderPage(seed: {
  orders?: Order[]
  invoices?: Invoice[]
  summary?: unknown[]
}): string {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } }
  })
  queryClient.setQueryData(['orders'], seed.orders ?? [])
  queryClient.setQueryData(['invoices'], seed.invoices ?? [])
  queryClient.setQueryData(['sales-summary'], seed.summary ?? [])

  return renderToString(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <SalesmanDashboardPage />
      </MemoryRouter>
    </QueryClientProvider>
  )
}

const order = {
  id: 1,
  number: 'SO/26-27/00001',
  customer_name: 'Retailer A',
  state: 'SUBMITTED',
  total_value: '7500.00',
  created_at: '2026-11-24T05:00:00Z'
} as unknown as Order

const invoice = {
  id: 1,
  number: 'INV/26-27/00001',
  customer_name: 'Retailer A',
  invoice_date: '2026-11-24',
  total: '7875.00',
  is_cancelled: false
} as unknown as Invoice

describe('SalesmanDashboardPage', () => {
  it('shows the salesman their recent orders and invoices', () => {
    const html = renderPage({
      orders: [order],
      invoices: [invoice],
      summary: [
        {
          customer_id: 1,
          customer_name: 'Retailer A',
          order_count: 1,
          total_qty: '150.000',
          total_value: '7500.00'
        }
      ]
    })

    expect(html).toContain('My dashboard')
    expect(html).toContain('SO/26-27/00001')
    expect(html).toContain('INV/26-27/00001')
    expect(html).toContain('7,500.00')
    expect(html).toContain('7,875.00')
  })

  it('still shows headings and empty states when there is no data', () => {
    const html = renderPage({})

    expect(html).toContain('My dashboard')
    expect(html).toContain('No orders yet. Create your first order.')
    expect(html).toContain('No invoices yet.')
    expect(html).toContain('No sales this month yet.')
  })
})
