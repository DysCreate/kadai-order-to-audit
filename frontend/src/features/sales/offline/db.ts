import Dexie, { type Table } from 'dexie'
import type { CatalogCacheRow, CustomerCacheRow, OutboxStore, QueuedOrder } from './types'

/**
 * Local store for the salesman PWA.
 *
 * The API remains the source of truth. This database only keeps (a) the last
 * catalog the server sent, so the order screen opens offline, and (b) orders
 * that have not reached the server yet. Every queued order carries the same
 * client UUID it will be submitted with, which is what makes a retry safe.
 */
export class KadaiDatabase extends Dexie {
  customers!: Table<CustomerCacheRow, string>
  catalog!: Table<CatalogCacheRow, string>
  outbox!: Table<QueuedOrder, string>

  constructor() {
    super('kadai')
    this.version(1).stores({
      customers: 'key',
      catalog: 'key, customer_id, version',
      outbox: 'id, created_at'
    })
    // v2 namespaces the outbox by owner so a shared device only syncs the
    // signed-in salesman's orders.
    this.version(2).stores({
      customers: 'key',
      catalog: 'key, customer_id, version',
      outbox: 'id, owner, created_at'
    })
  }
}

export const db = new KadaiDatabase()

export const dexieOutbox: OutboxStore = {
  async put(order: QueuedOrder) {
    await db.outbox.put(order)
  },
  async all() {
    return db.outbox.toArray()
  },
  async remove(id: string) {
    await db.outbox.delete(id)
  },
  async markError(id: string, message: string) {
    await db.outbox.update(id, { last_error: message })
  }
}

const customersKey = (owner: string) => `customers:${owner}`
const catalogKey = (owner: string, customerId: number) => `customer:${owner}:${customerId}`

export async function saveCustomers(owner: string, rows: CustomerCacheRow['rows']): Promise<void> {
  await db.customers.put({
    key: customersKey(owner),
    rows,
    fetched_at: new Date().toISOString()
  })
}

export async function readCustomers(owner: string): Promise<CustomerCacheRow | undefined> {
  return db.customers.get(customersKey(owner))
}

export async function saveCatalog(
  owner: string,
  customerId: number,
  version: string,
  rows: CatalogCacheRow['rows']
): Promise<void> {
  await db.catalog.put({
    key: catalogKey(owner, customerId),
    customer_id: customerId,
    version,
    rows,
    fetched_at: new Date().toISOString()
  })
}

export async function readCatalog(
  owner: string,
  customerId: number
): Promise<CatalogCacheRow | undefined> {
  return db.catalog.get(catalogKey(owner, customerId))
}

export async function countQueuedOrders(owner: string): Promise<number> {
  return db.outbox.where('owner').equals(owner).count()
}
