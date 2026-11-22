import { describe, expect, it } from 'vitest'
import { reportDownloadUrl } from './reportsApi'

describe('reportDownloadUrl', () => {
  it('encodes the report format and date range for a download link', () => {
    expect(
      reportDownloadUrl('sales-register', 'excel', {
        date_from: '2026-05-01',
        date_to: '2026-05-31'
      })
    ).toBe('/api/reports/sales-register/?format=excel&date_from=2026-05-01&date_to=2026-05-31')
  })

  it('omits an empty range', () => {
    expect(reportDownloadUrl('stock-summary', 'csv')).toBe(
      '/api/reports/stock-summary/?format=csv'
    )
  })
})
