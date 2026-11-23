import { createOrder, type CreateOrderInput } from '../salesApi'
import { countQueuedOrders, dexieOutbox } from './db'
import { buildQueuedOrder, flushOutbox, type FlushResult } from './outbox'

export const OUTBOX_EVENT = 'kadai:outbox-changed'
const BACKGROUND_SYNC_TAG = 'kadai-order-sync'

const inFlight = new Map<string, Promise<FlushResult>>()

export function notifyOutboxChanged(): void {
  window.dispatchEvent(new Event(OUTBOX_EVENT))
}

/** Queue one order under its own client UUID, safe to replay after a reload. */
export async function enqueueOrder(
  payload: CreateOrderInput,
  customerName: string,
  owner: string
): Promise<void> {
  await dexieOutbox.put(buildQueuedOrder(payload, customerName, owner))
  notifyOutboxChanged()
  void requestBackgroundSync()
}

/**
 * Submit every queued order once. Concurrent callers share the same flush, so
 * the online event, the badge and the service-worker wake-up cannot send the
 * same UUID twice in parallel.
 */
export function syncQueuedOrders(owner: string): Promise<FlushResult> {
  const running = inFlight.get(owner)
  if (running) return running
  const flushed = flushOutbox(dexieOutbox, createOrder, owner).finally(() => {
    inFlight.delete(owner)
    notifyOutboxChanged()
  })
  inFlight.set(owner, flushed)
  return flushed
}

export async function pendingOrderCount(owner: string): Promise<number> {
  return countQueuedOrders(owner)
}

/**
 * Ask the browser to wake the app when connectivity returns. Browsers without
 * Background Sync still sync on the app's own ``online`` event.
 */
export async function requestBackgroundSync(): Promise<void> {
  if (typeof navigator === 'undefined' || !('serviceWorker' in navigator)) return
  try {
    const registration = await navigator.serviceWorker.getRegistration()
    if (!registration) return
    const manager = (
      registration as ServiceWorkerRegistration & {
        sync?: { register(tag: string): Promise<void> }
      }
    ).sync
    await manager?.register(BACKGROUND_SYNC_TAG)
  } catch {
    // Unsupported or denied Background Sync is not an error; the online
    // listener remains the primary trigger.
  }
}
