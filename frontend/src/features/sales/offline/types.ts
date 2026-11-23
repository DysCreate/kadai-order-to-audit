import type { CatalogItem, CreateOrderInput, Customer } from '../salesApi'

/** Customers cached for one salesman's offline customer picker. */
export interface CustomerCacheRow {
  key: string
  rows: Customer[]
  fetched_at: string
}

/**
 * A customer's priced catalog, stamped with the price list version it came
 * from, so a price-list change is never mistaken for a stale cache hit.
 */
export interface CatalogCacheRow {
  key: string
  customer_id: number
  version: string
  rows: CatalogItem[]
  fetched_at: string
}

/**
 * An order waiting for the network. Its id is the server's client UUID and
 * ``owner`` is the username that took it, so a shared device never syncs or
 * shows another salesman's queued orders.
 */
export interface QueuedOrder {
  id: string
  owner: string
  payload: CreateOrderInput
  customer_name: string
  created_at: string
  last_error: string
}

/** The outbox operations the flush logic needs; Dexie implements this. */
export interface OutboxStore {
  put(order: QueuedOrder): Promise<void>
  all(): Promise<QueuedOrder[]>
  remove(id: string): Promise<void>
  markError(id: string, message: string): Promise<void>
}
