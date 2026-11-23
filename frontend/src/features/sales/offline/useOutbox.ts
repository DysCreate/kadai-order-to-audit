import { useCallback, useEffect, useState } from 'react'
import { OUTBOX_EVENT, pendingOrderCount, syncQueuedOrders } from './sync'

export function useOnline(): boolean {
  const [online, setOnline] = useState(() =>
    typeof navigator === 'undefined' ? true : navigator.onLine
  )

  useEffect(() => {
    const goOnline = () => setOnline(true)
    const goOffline = () => setOnline(false)
    window.addEventListener('online', goOnline)
    window.addEventListener('offline', goOffline)
    return () => {
      window.removeEventListener('online', goOnline)
      window.removeEventListener('offline', goOffline)
    }
  }, [])

  return online
}

/**
 * Pending-order count plus a manual sync for the signed-in user. The same
 * flush runs on mount, on the ``online`` event and when the service worker
 * wakes the page via Background Sync; the runner itself is a no-op the second
 * time. Another user's queued orders are never counted or sent.
 */
export function useOutbox(owner: string | undefined) {
  const [pending, setPending] = useState(0)
  const [syncing, setSyncing] = useState(false)
  const [failed, setFailed] = useState(0)
  const [error, setError] = useState<string | null>(null)

  const refresh = useCallback(async () => {
    if (!owner) return
    try {
      setPending(await pendingOrderCount(owner))
    } catch {
      // IndexedDB can be unavailable (private mode); ordering still works
      // online, so the badge simply stays hidden.
    }
  }, [owner])

  const sync = useCallback(async () => {
    if (!owner) return
    setSyncing(true)
    setError(null)
    try {
      const result = await syncQueuedOrders(owner)
      setFailed(result.failed.length)
    } catch {
      setError('sync-failed')
    } finally {
      setSyncing(false)
      await refresh()
    }
  }, [owner, refresh])

  useEffect(() => {
    void refresh()
    void sync()

    const onOnline = () => void sync()
    const onChanged = () => void refresh()
    const onMessage = (event: MessageEvent) => {
      const data = event.data as { type?: string } | undefined
      if (data?.type === 'kadai:sync-orders') void sync()
    }

    window.addEventListener('online', onOnline)
    window.addEventListener(OUTBOX_EVENT, onChanged)
    navigator.serviceWorker?.addEventListener('message', onMessage)
    return () => {
      window.removeEventListener('online', onOnline)
      window.removeEventListener(OUTBOX_EVENT, onChanged)
      navigator.serviceWorker?.removeEventListener('message', onMessage)
    }
  }, [refresh, sync])

  return { pending, syncing, failed, error, sync, refresh }
}
