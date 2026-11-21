const formatter = new Intl.NumberFormat('en-IN', {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2
})

/**
 * Format a server-provided Decimal string for display.
 *
 * The frontend never does money arithmetic: every amount shown here comes from
 * the API, and this helper only localises it for India.
 */
export function formatMoney(value: string | null | undefined): string {
  if (value === null || value === undefined || value === '') return '—'
  return formatter.format(Number(value))
}
