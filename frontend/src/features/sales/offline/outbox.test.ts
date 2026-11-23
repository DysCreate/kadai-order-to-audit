import { describe, expect, it, vi } from 'vitest'
import type { CreateOrderInput } from '../salesApi'
import { buildQueuedOrder, flushOutbox, isNetworkError } from './outbox'
import type { OutboxStore, QueuedOrder } from './types'

function payload(uuid: string): CreateOrderInput {
  return { client_uuid: uuid, customer: 1, lines: [{ item: 1, qty: '150' }] }
}

class MemoryOutbox implements OutboxStore {
  rows: QueuedOrder[] = []
  errors: Record<string, string> = {}
  async put(order: QueuedOrder) {
    this.rows = [...this.rows.filter((row) => row.id !== order.id), order]
  }
  async all() {
    return this.rows
  }
  async remove(id: string) {
    this.rows = this.rows.filter((row) => row.id !== id)
  }
  async markError(id: string, message: string) {
    this.errors[id] = message
  }
}

function networkFailure(): Error {
  return Object.assign(new Error('Network Error'), { isAxiosError: true })
}

function refused(): Error {
  return Object.assign(new Error('Bad request'), {
    isAxiosError: true,
    response: {
      data: { detail: 'No selling price is configured for this item.' },
      status: 400,
      statusText: 'Bad Request'
    }
  })
}

describe('isNetworkError', () => {
  it('treats a request that never got a response as a network failure', () => {
    expect(isNetworkError(networkFailure())).toBe(true)
  })

  it('treats an HTTP refusal as a server answer, not a network failure', () => {
    expect(isNetworkError(refused())).toBe(false)
  })

  it('treats a fetch TypeError as a network failure', () => {
    expect(isNetworkError(new TypeError('Failed to fetch'))).toBe(true)
  })
})

describe('buildQueuedOrder', () => {
  it('uses the client UUID as the queue id so a retry cannot duplicate', () => {
    const row = buildQueuedOrder(
      payload('uuid-1'),
      'Retailer A',
      'salesman_a',
      new Date('2026-06-01T10:00:00Z')
    )
    expect(row.id).toBe('uuid-1')
    expect(row.owner).toBe('salesman_a')
    expect(row.payload.client_uuid).toBe('uuid-1')
    expect(row.customer_name).toBe('Retailer A')
    expect(row.created_at).toBe('2026-06-01T10:00:00.000Z')
  })
})

describe('flushOutbox', () => {
  it('submits oldest first and clears each successful order', async () => {
    const store = new MemoryOutbox()
    await store.put(
      buildQueuedOrder(payload('second'), 'B', 'salesman_a', new Date('2026-06-01T10:00:02Z'))
    )
    await store.put(
      buildQueuedOrder(payload('first'), 'A', 'salesman_a', new Date('2026-06-01T10:00:01Z'))
    )
    const sent: string[] = []

    const result = await flushOutbox(store, async (order) => {
      sent.push(order.client_uuid)
    })

    expect(sent).toEqual(['first', 'second'])
    expect(result.synced).toEqual(['first', 'second'])
    expect(store.rows).toEqual([])
  })

  it('stops on a network failure and keeps the remaining orders queued', async () => {
    const store = new MemoryOutbox()
    await store.put(
      buildQueuedOrder(payload('first'), 'A', 'salesman_a', new Date('2026-06-01T10:00:01Z'))
    )
    await store.put(
      buildQueuedOrder(payload('second'), 'B', 'salesman_a', new Date('2026-06-01T10:00:02Z'))
    )
    const submit = vi.fn().mockRejectedValue(networkFailure())

    const result = await flushOutbox(store, submit)

    expect(submit).toHaveBeenCalledTimes(1)
    expect(result).toEqual({ synced: [], failed: [] })
    expect(store.rows.map((row) => row.id)).toEqual(['first', 'second'])
  })

  it('keeps a refused order with its server message and continues', async () => {
    const store = new MemoryOutbox()
    await store.put(
      buildQueuedOrder(payload('refused'), 'A', 'salesman_a', new Date('2026-06-01T10:00:01Z'))
    )
    await store.put(
      buildQueuedOrder(payload('fine'), 'B', 'salesman_a', new Date('2026-06-01T10:00:02Z'))
    )

    const result = await flushOutbox(store, async (order) => {
      if (order.client_uuid === 'refused') throw refused()
    })

    expect(result.synced).toEqual(['fine'])
    expect(result.failed).toEqual(['refused'])
    expect(store.rows.map((row) => row.id)).toEqual(['refused'])
    expect(store.errors.refused).toBe('No selling price is configured for this item.')
  })

  it('only sends the signed-in salesman\'s orders', async () => {
    const store = new MemoryOutbox()
    await store.put(
      buildQueuedOrder(payload('mine'), 'A', 'salesman_a', new Date('2026-06-01T10:00:01Z'))
    )
    await store.put(
      buildQueuedOrder(payload('theirs'), 'B', 'salesman_b', new Date('2026-06-01T10:00:02Z'))
    )
    const sent: string[] = []

    const result = await flushOutbox(store, async (order) => {
      sent.push(order.client_uuid)
    }, 'salesman_a')

    expect(sent).toEqual(['mine'])
    expect(result.synced).toEqual(['mine'])
    expect(store.rows.map((row) => row.id)).toEqual(['theirs'])
  })
})
