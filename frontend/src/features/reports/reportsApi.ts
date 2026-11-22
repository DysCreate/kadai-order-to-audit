import apiClient from '../../lib/apiClient'

export type ColumnKind =
  | 'text'
  | 'money'
  | 'qty'
  | 'rate'
  | 'int'
  | 'date'
  | 'bool'
  | 'percent'
  | 'variance'

export interface ReportColumn {
  key: string
  label: string
  kind: ColumnKind
}

export interface ReportDefinition {
  slug: string
  title: string
  columns: ReportColumn[]
}

export interface Report {
  slug: string
  title: string
  columns: ReportColumn[]
  rows: Record<string, string>[]
  totals: Record<string, string>
  meta: Record<string, unknown>
  date_from: string | null
  date_to: string | null
}

export interface DateRange {
  date_from?: string
  date_to?: string
}

export interface ReconciliationCheck {
  name: string
  expected: string
  actual: string
  passed: boolean
  detail: string
}

export interface DashboardStockRow {
  item_id: number
  item_name: string
  item_type: string
  uom: string
  qty: string
  value: string
  reorder: boolean
  reorder_qty: string
  batch_requirement: string | null
}

export interface DashboardVarianceAlert {
  run_id: number
  product: string
  item_name: string
  kind: string
  variance_pct: string
  direction: string
}

export interface Dashboard {
  business_date: string
  today_orders: { count: number; value: string }
  open_orders: { count: number; submitted: number; approved: number }
  stock: DashboardStockRow[]
  reorder_count: number
  variance_alerts: DashboardVarianceAlert[]
  cost_per_packet: {
    run_id: number
    product: string
    cost_per_packet: string
    selling_price: string | null
    margin_per_packet: string | null
    margin_pct: string | null
  } | null
  outstanding_dues: { amount: string; customers: number }
  leakage: {
    period: string
    amount: string
    runs: number
    top_culprits: { label: string; amount: string }[]
  }
}

export async function listReports(): Promise<ReportDefinition[]> {
  const res = await apiClient.get<ReportDefinition[]>('/reports/')
  return res.data
}

export async function getReport(slug: string, range: DateRange = {}): Promise<Report> {
  const res = await apiClient.get<Report>(`/reports/${slug}/`, {
    params: { ...range }
  })
  return res.data
}

export async function getReconciliation(range: DateRange = {}): Promise<ReconciliationCheck[]> {
  const res = await apiClient.get<ReconciliationCheck[]>('/reports/reconciliation/', {
    params: { ...range }
  })
  return res.data
}

export async function getDashboard(): Promise<Dashboard> {
  const res = await apiClient.get<Dashboard>('/reports/dashboard/')
  return res.data
}

/**
 * Build a same-origin download URL for a report export.
 *
 * GET downloads ride the session cookie, so a plain anchor works; the server
 * sets Content-Disposition with the report and period in the filename.
 */
export function reportDownloadUrl(
  slug: string,
  format: 'csv' | 'excel' | 'pdf',
  range: DateRange = {}
): string {
  const params = new URLSearchParams({ format })
  if (range.date_from) params.set('date_from', range.date_from)
  if (range.date_to) params.set('date_to', range.date_to)
  return `/api/reports/${slug}/?${params.toString()}`
}
