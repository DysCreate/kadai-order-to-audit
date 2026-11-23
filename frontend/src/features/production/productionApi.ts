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

export interface BomLine {
  id: number
  item_id: number
  item_name: string
  uom: string
  role: RunLineRole
  qty_per_batch: string
  standard_rate: string
}

export interface Bom {
  id: number
  product_id: number
  product_name: string
  version: number
  batch_output_qty: string
  created_at: string
  lines: BomLine[]
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

export async function listBoms(): Promise<Bom[]> {
  const res = await apiClient.get<Bom[]>('/production/boms/')
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

export interface ReportCardLine {
  item_id: number
  item_name: string
  role: RunLineRole
  planned_qty: string
  actual_qty: string
  standard_rate: string
  actual_rate: string
  standard_value: string
  actual_value: string
  price_impact: string
  usage_impact: string
  total_impact: string
}

export interface BridgeStep {
  key: 'standard_material' | 'yield_shortfall' | 'price_usage' | 'overhead'
  label: string
  amount: string
  cumulative: string
}

export interface YieldGap {
  planned_packets: string
  good_packets: string
  gap_packets: string
  damaged_packets: string
  unexplained_packets: string
}

export interface ReportCard {
  lines: ReportCardLine[]
  standard_materials: string
  actual_materials: string
  price_impact: string
  usage_impact: string
  material_impact: string
  planned_packets: string
  good_packets: string
  overhead_value: string
  standard_per_packet: string
  actual_material_per_packet: string
  overhead_per_packet: string
  cost_per_packet: string
  bridge: BridgeStep[]
  yield_gap: YieldGap
  selling_price: string | null
  margin_per_packet: string | null
  margin_pct: string | null
}

export interface VariancePoint {
  run_id: number
  variance_pct: string | null
  direction: VarianceDirection
}

export interface IngredientTrend {
  item_name: string
  points: VariancePoint[]
}

export interface DriftAlert {
  item_name: string
  consecutive_runs: number
  latest_variance_pct: string | null
  threshold: string
  direction: VarianceDirection
}

export interface LeakageTrends {
  product_id: number
  product_name: string
  runs: { run_id: number; completed_at: string | null }[]
  ingredients: IngredientTrend[]
  drift_alerts: DriftAlert[]
  tolerance: string
}

export async function getRunReportCard(id: number): Promise<ReportCard> {
  const res = await apiClient.get<ReportCard>(`/production/runs/${id}/report-card/`)
  return res.data
}

export async function getProductLeakage(id: number): Promise<LeakageTrends> {
  const res = await apiClient.get<LeakageTrends>(`/production/products/${id}/leakage/`)
  return res.data
}

export async function createRun(productId: number, batches: string): Promise<ProductionRun> {
  const res = await apiClient.post<ProductionRun>('/production/runs/', {
    product: productId,
    batches
  })
  return res.data
}
