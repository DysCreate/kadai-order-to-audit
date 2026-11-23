import axios from 'axios'
import type { CreateOrderInput } from '../salesApi'
import type { OutboxStore, QueuedOrder } from './types'

export interface FlushResult {
  synced: string[]
  failed: string[]
}

/**
 * A network failure means the request never reached the server; anything else
 * (a 4xx or 5xx answer) means the server saw it and refused it.
 */
export function isNetworkError(error: unknown): boolean {
  if (axios.isAxiosError(error)) return error.response === undefined
  return error instanceof TypeError
}

export function errorMessage(error: unknown, fallback: string): string {
  if (axios.isAxiosError(error)) {
    const detail = (error.response?.data as { detail?: unknown } | undefined)?.detail
    if (typeof detail === 'string' && detail.length > 0) return detail
    return error.message || fallback
  }
  if (error instanceof Error && error.message) return error.message
  return fallback
}

/** Freeze the order exactly as it was taken, with a durable client UUID. */
export function buildQueuedOrder(
  payload: CreateOrderInput,
  customerName: string,
  owner: string,
  now: Date = new Date()
): QueuedOrder {
  return {
    id: payload.client_uuid,
    owner,
    payload,
    customer_name: customerName,
    created_at: now.toISOString(),
    last_error: ''
  }
}

/**
 * Submit queued orders oldest first.
 *
 * - Success (including an idempotent replay of the same client UUID) removes
 *   the row, so a retry can never create a duplicate order.
 * - A network error stops the flush and keeps the row for the next attempt.
 * - A refused order stays queued with its error so an operator can inspect it
 *   rather than silently losing the sale.
 */
export async function flushOutbox(
  store: OutboxStore,
  submit: (payload: CreateOrderInput) => Promise<unknown>,
  owner?: string,
  fallbackMessage = 'Could not sync this order.'
): Promise<FlushResult> {
  const rows = (await store.all())
    .filter((row) => owner === undefined || row.owner === owner)
    .sort((a, b) => a.created_at.localeCompare(b.created_at))
  const result: FlushResult = { synced: [], failed: [] }

  for (const row of rows) {
    try {
      await submit(row.payload)
      await store.remove(row.id)
      result.synced.push(row.id)
    } catch (error) {
      if (isNetworkError(error)) break
      result.failed.push(row.id)
      await store.markError(row.id, errorMessage(error, fallbackMessage))
    }
  }

  return result
}
