import apiClient from '../../lib/apiClient'

export type RunState = 'DRAFT' | 'ISSUED' | 'COMPLETED'
export type RunLineRole = 'material' | 'pouch' | 'carton'
export type VarianceDirection = 'favourable' | 'adverse' | 'none'

export interface RunLine {
  id: number
  item_id: number
  item_name: string
  uom: string
  role: RunLineRole
  planned_qty: string
  issued_qty: string
  actual_qty: string
  issued_unit_value: string | null
}

export interface VarianceRow {
  line_id: number | null
  kind: 'usage' | 'yield'
  item_name: string
  planned_qty: string
  actual_qty: string
  variance_pct: string | null
  flagged: boolean
  direction: VarianceDirection
}

export interface ProductionRun {
  id: number
  product_id: number
  product_name: string
  bom_version: number
  batches: string
  planned_output_qty: string
  state: RunState
  good_packets: string | null
  damaged_pouches: string | null
  cartons_used: string | null
  revision: number
  created_at: string
  issued_at: string | null
  completed_at: string | null
  lines: RunLine[]
  variance: VarianceRow[]
  tolerance: string
}

export interface IssueLineInput {
  line: number
  qty: string
}

export interface CompleteRunInput {
  good_packets: string
  damaged_pouches: string
  cartons_used: string
}

export async function listRuns(): Promise<ProductionRun[]> {
  const res = await apiClient.get<ProductionRun[]>('/production/runs/')
  return res.data
}

export async function getRun(id: number): Promise<ProductionRun> {
  const res = await apiClient.get<ProductionRun>(`/production/runs/${id}/`)
  return res.data
}

export async function issueRun(id: number, lines: IssueLineInput[]): Promise<ProductionRun> {
  const res = await apiClient.post<ProductionRun>(`/production/runs/${id}/issue/`, { lines })
  return res.data
}

export async function completeRun(id: number, input: CompleteRunInput): Promise<ProductionRun> {
  const res = await apiClient.post<ProductionRun>(`/production/runs/${id}/complete/`, input)
  return res.data
}

export async function amendRun(id: number, reason: string): Promise<ProductionRun> {
  const res = await apiClient.post<ProductionRun>(`/production/runs/${id}/amend/`, { reason })
  return res.data
}
