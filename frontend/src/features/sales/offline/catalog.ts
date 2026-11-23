import { listCustomers, listSellableItems, type CatalogItem, type Customer } from '../salesApi'
import { readCatalog, readCustomers, saveCatalog, saveCustomers } from './db'
import { isNetworkError } from './outbox'

/**
 * Load the salesman's customers, writing through to IndexedDB. On a network
 * failure the last successful response is used; any other error still
 * surfaces so a permission or server problem is never mistaken for "offline".
 */
export async function loadCustomers(
  owner: string,
  fetcher: () => Promise<Customer[]> = listCustomers
): Promise<Customer[]> {
  try {
    const rows = await fetcher()
    await saveCustomers(owner, rows)
    return rows
  } catch (error) {
    if (!isNetworkError(error)) throw error
    const cached = await readCustomers(owner)
    if (!cached) throw error
    return cached.rows
  }
}

/**
 * Load a customer's priced catalog. ``version`` is the price-list stamp the
 * rows belong to; stored rows from another version are replaced on the next
 * successful fetch. Offline, the last cached version is shown.
 */
export async function loadCatalog(
  owner: string,
  customerId: number,
  version: string,
  fetcher: () => Promise<CatalogItem[]> = () => listSellableItems(customerId)
): Promise<CatalogItem[]> {
  try {
    const rows = await fetcher()
    await saveCatalog(owner, customerId, version, rows)
    return rows
  } catch (error) {
    if (!isNetworkError(error)) throw error
    const cached = await readCatalog(owner, customerId)
    if (!cached) throw error
    return cached.rows
  }
}
