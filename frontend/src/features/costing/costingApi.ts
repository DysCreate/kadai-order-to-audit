import apiClient from '../../lib/apiClient'

export type OverheadCategory = 'labour' | 'power' | 'other'
export type OverheadScope = 'RUN' | 'MONTH'

export interface MaterialLine {
  item_id: number
  item_name: string
  uom: string
  qty: string
  value: string
}

export interface OverheadLine {
  entry_id: number
  allocation_id: number | null
  scope: OverheadScope
  category: OverheadCategory
  amount: string
  description: string
  period: string | null
}

export interface CostSheet {
  run_id: number
  product_id: number
  product_name: string
  product_uom: string
  state: string
  batches: string
  standard_batch_hours: string
  batch_hours: string
  good_packets: string
  materials: MaterialLine[]
  materials_value: string
  overheads: OverheadLine[]
  overhead_value: string
  total_cost: string
  cost_per_packet: string
  selling_price: string | null
  margin_per_packet: string | null
  margin_pct: string | null
  fg_stock_qty: string
  fg_stock_value: string
  fg_avg_cost: string
}

export interface ProductCost {
  product_id: number
  product_name: string
  stock_qty: string
  stock_value: string
  avg_cost: string
  selling_price: string | null
  margin_per_packet: string | null
  margin_pct: string | null
}

export interface RunOverheadInput {
  category: OverheadCategory
  amount: string
  description: string
}

export async function getCostSheet(runId: number): Promise<CostSheet> {
  const res = await apiClient.get<CostSheet>(`/costing/runs/${runId}/`)
  return res.data
}

export async function addRunOverhead(
  runId: number,
  input: RunOverheadInput
): Promise<CostSheet> {
  const res = await apiClient.post<CostSheet>(`/costing/runs/${runId}/overheads/`, input)
  return res.data
}

export async function getProductCost(productId: number): Promise<ProductCost> {
  const res = await apiClient.get<ProductCost>(`/costing/products/${productId}/`)
  return res.data
}
