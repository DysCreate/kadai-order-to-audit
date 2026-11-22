import apiClient from '../../lib/apiClient'

export type OrderState = 'SUBMITTED' | 'APPROVED' | 'REJECTED' | 'INVOICED' | 'DISPATCHED'

export interface Customer {
  id: number
  name: string
  gstin: string
  state_code: string
  customer_type: string
  price_list_id: number | null
  assigned_salesman: string | null
}

export interface CatalogItem {
  id: number
  name: string
  item_type: string
  uom: string
  hsn_code: string
  gst_rate: string
  price: string | null
}

export interface OrderLine {
  id: number
  item_id: number
  item_name: string
  uom: string
  qty: string
  unit_price: string
  gst_rate: string
  line_value: string
}

export interface Order {
  id: number
  number: string
  client_uuid: string
  customer_id: number
  customer_name: string
  customer_state_code: string
  salesman_username: string
  state: OrderState
  notes: string
  rejection_reason: string
  created_at: string
  updated_at: string
  approved_at: string | null
  lines: OrderLine[]
  total_value: string
}

export interface TaxPreview {
  is_interstate: boolean
  taxable_total: string
  cgst_total: string
  sgst_total: string
  igst_total: string
  round_off: string
  total: string
}

export interface CustomerSalesRow {
  customer_id: number
  customer_name: string
  order_count: number
  total_qty: string
  total_value: string
}

export interface CoverageLine {
  line_id: number
  item_id: number
  item_name: string
  uom: string
  ordered_qty: string
  on_hand_qty: string
  committed_qty: string
  available_qty: string
  shortage_qty: string
}

export interface CapacityRow {
  item_id: number
  item_name: string
  uom: string
  qty_per_batch: string
  stock_qty: string
  batches_available: number
  ratio: string
  limiting: boolean
}

export interface PurchaseSuggestion {
  item_id: number
  item_name: string
  uom: string
  qty: string
}

export interface LoopCloser {
  product_id: number
  product_name: string
  shortage_qty: string
  batch_output_qty: string
  yield_factor: string
  batches_needed: number
  batches_allowed: number
  feasible: boolean
  limiting_item: string
  capacity: CapacityRow[]
  purchase_list: PurchaseSuggestion[]
  verdict: 'feasible' | 'purchase_needed' | 'insufficient_stock' | 'nothing_to_produce'
}

export interface OrderCoverage {
  lines: CoverageLine[]
  total_shortage_qty: string
  is_interstate: boolean
  tax_preview: TaxPreview
  loop_closers: LoopCloser[]
}

export interface InvoiceLine {
  id: number
  item_id: number
  item_name: string
  uom: string
  description: string
  hsn_code: string
  qty: string
  unit_price: string
  gst_rate: string
  taxable_value: string
  cgst: string
  sgst: string
  igst: string
  line_total: string
  dispatched_qty: string
  credited_qty: string
  remaining_qty: string
}

export interface DispatchLine {
  id: number
  invoice_line_id: number
  item_name: string
  qty: string
}

export interface Dispatch {
  id: number
  invoice_id: number
  invoice_number: string
  dispatch_date: string
  notes: string
  created_at: string
  lines: DispatchLine[]
}

export interface CreditNoteLine {
  id: number
  invoice_line_id: number
  item_name: string
  qty: string
  taxable_value: string
  cgst: string
  sgst: string
  igst: string
  line_total: string
}

export interface CreditNote {
  id: number
  number: string
  invoice_id: number
  invoice_number: string
  reason: string
  restock: boolean
  taxable_total: string
  cgst_total: string
  sgst_total: string
  igst_total: string
  round_off: string
  total: string
  created_at: string
  lines: CreditNoteLine[]
}

export interface Invoice {
  id: number
  number: string
  order_id: number
  customer_id: number
  customer_name: string
  customer_gstin: string
  customer_state_code: string
  invoice_date: string
  place_of_supply_state_code: string
  is_interstate: boolean
  taxable_total: string
  cgst_total: string
  sgst_total: string
  igst_total: string
  round_off: string
  total: string
  amount_in_words: string
  is_cancelled: boolean
  credited_total: string
  dispatched_total: string
  created_at: string
  lines: InvoiceLine[]
  credit_notes: CreditNote[]
  dispatches: Dispatch[]
}

export interface PaymentAllocation {
  id: number
  invoice_id: number
  invoice_number: string
  amount: string
}

export interface Payment {
  id: number
  customer_id: number
  customer_name: string
  amount: string
  payment_date: string
  method: string
  reference: string
  notes: string
  created_at: string
  allocations: PaymentAllocation[]
}

export interface AgeingBucket {
  label: string
  amount: string
}

export interface LedgerInvoice {
  invoice_id: number
  number: string
  invoice_date: string
  total: string
  credited: string
  paid: string
  outstanding: string
  age_days: number
}

export interface CustomerLedger {
  customer_id: number
  customer_name: string
  outstanding: string
  buckets: AgeingBucket[]
  invoices: LedgerInvoice[]
  payments: Payment[]
}

export interface OrderLineInput {
  item: number
  qty: string
}

export interface CreateOrderInput {
  client_uuid: string
  customer: number
  notes?: string
  lines: OrderLineInput[]
}

export interface DispatchInput {
  dispatch_date?: string
  notes?: string
  lines: { invoice_line: number; qty: string }[]
}

export interface CreditNoteInput {
  reason: string
  restock: boolean
  note_date?: string
  lines: { invoice_line: number; qty: string }[]
}

export interface PaymentInput {
  customer: number
  amount: string
  method: string
  payment_date?: string
  reference?: string
  notes?: string
  allocations: { invoice: number; amount: string }[]
}

export interface ShareLinks {
  pdf_url: string
  whatsapp: string
  mailto: string
}

export async function listCustomers(): Promise<Customer[]> {
  const res = await apiClient.get<Customer[]>('/masters/customers/')
  return res.data
}

export async function listSellableItems(customerId?: number): Promise<CatalogItem[]> {
  const res = await apiClient.get<CatalogItem[]>('/masters/items/', {
    params: { type: 'FG', ...(customerId ? { customer: customerId } : {}) }
  })
  return res.data
}

export async function listOrders(params: { state?: OrderState; customer?: number } = {}): Promise<
  Order[]
> {
  const res = await apiClient.get<Order[]>('/sales/orders/', { params })
  return res.data
}

export async function getOrder(id: number): Promise<Order> {
  const res = await apiClient.get<Order>(`/sales/orders/${id}/`)
  return res.data
}

export async function createOrder(input: CreateOrderInput): Promise<Order> {
  const res = await apiClient.post<Order>('/sales/orders/', input)
  return res.data
}

export async function getSalesSummary(month?: string): Promise<CustomerSalesRow[]> {
  const res = await apiClient.get<CustomerSalesRow[]>('/sales/orders/summary/', {
    params: month ? { month } : {}
  })
  return res.data
}

export async function getOrderCoverage(id: number): Promise<OrderCoverage> {
  const res = await apiClient.get<OrderCoverage>(`/sales/orders/${id}/coverage/`)
  return res.data
}

export async function approveOrder(id: number): Promise<Order> {
  const res = await apiClient.post<Order>(`/sales/orders/${id}/approve/`, {})
  return res.data
}

export async function rejectOrder(id: number, reason: string): Promise<Order> {
  const res = await apiClient.post<Order>(`/sales/orders/${id}/reject/`, { reason })
  return res.data
}

export async function editOrderLine(
  orderId: number,
  lineId: number,
  changes: { qty?: string; unit_price?: string }
): Promise<Order> {
  const res = await apiClient.patch<Order>(`/sales/orders/${orderId}/lines/${lineId}/`, changes)
  return res.data
}

export async function createInvoice(orderId: number, invoiceDate?: string): Promise<Invoice> {
  const res = await apiClient.post<Invoice>(`/sales/orders/${orderId}/invoice/`, {
    ...(invoiceDate ? { invoice_date: invoiceDate } : {})
  })
  return res.data
}

export async function listInvoices(): Promise<Invoice[]> {
  const res = await apiClient.get<Invoice[]>('/sales/invoices/')
  return res.data
}

export async function getInvoice(id: number): Promise<Invoice> {
  const res = await apiClient.get<Invoice>(`/sales/invoices/${id}/`)
  return res.data
}

export async function dispatchInvoice(id: number, input: DispatchInput): Promise<Dispatch> {
  const res = await apiClient.post<Dispatch>(`/sales/invoices/${id}/dispatch/`, input)
  return res.data
}

export async function createCreditNote(id: number, input: CreditNoteInput): Promise<CreditNote> {
  const res = await apiClient.post<CreditNote>(`/sales/invoices/${id}/credit-notes/`, input)
  return res.data
}

export async function getShareLinks(id: number): Promise<ShareLinks> {
  const res = await apiClient.get<ShareLinks>(`/sales/invoices/${id}/share/`)
  return res.data
}

export async function listPayments(customerId?: number): Promise<Payment[]> {
  const res = await apiClient.get<Payment[]>('/payments/payments/', {
    params: customerId ? { customer: customerId } : {}
  })
  return res.data
}

export async function recordPayment(input: PaymentInput): Promise<Payment> {
  const res = await apiClient.post<Payment>('/payments/payments/', input)
  return res.data
}

export async function getOutstanding(
  customerId: number
): Promise<{ customer_id: number; customer_name: string; outstanding: string }> {
  const res = await apiClient.get('/payments/outstanding/', { params: { customer: customerId } })
  return res.data
}

export async function getAgeing(
  customerId: number,
  asOf?: string
): Promise<{ buckets: AgeingBucket[]; outstanding: string }> {
  const res = await apiClient.get('/payments/ageing/', {
    params: { customer: customerId, ...(asOf ? { as_of: asOf } : {}) }
  })
  return res.data
}

export async function getCustomerLedger(customerId: number): Promise<CustomerLedger> {
  const res = await apiClient.get<CustomerLedger>(`/payments/customers/${customerId}/ledger/`)
  return res.data
}

export function invoicePdfPath(invoiceId: number): string {
  return `/api/sales/invoices/${invoiceId}/pdf/`
}
