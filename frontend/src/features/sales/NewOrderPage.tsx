import { useMemo, useState, type FormEvent } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router-dom'
import { apiErrorMessage } from '../../lib/apiError'
import { formatMoney } from '../../lib/money'
import { LoadingPanel, SkeletonCardList } from '../../components/Skeleton'
import {
  createOrder,
  type CatalogItem,
  type CreateOrderInput,
  type Customer
} from './salesApi'
import { loadCatalog, loadCustomers } from './offline/catalog'
import { isNetworkError } from './offline/outbox'
import { enqueueOrder } from './offline/sync'
import { useOnline } from './offline/useOutbox'
import { useAuth } from '../auth/AuthContext'

const RECENTS_KEY = 'kadai.recentCustomers'

function readRecents(): number[] {
  try {
    const parsed: unknown = JSON.parse(localStorage.getItem(RECENTS_KEY) ?? '[]')
    return Array.isArray(parsed)
      ? parsed.filter((value): value is number => typeof value === 'number')
      : []
  } catch {
    return []
  }
}

function rememberCustomer(customerId: number): void {
  const next = [customerId, ...readRecents().filter((id) => id !== customerId)].slice(0, 4)
  localStorage.setItem(RECENTS_KEY, JSON.stringify(next))
}

function Stepper({
  item,
  value,
  onChange
}: {
  item: CatalogItem
  value: string
  onChange: (value: string) => void
}) {
  const { t } = useTranslation()
  const step = (delta: number) => {
    const current = Number(value || '0')
    const next = Math.max(0, current + delta)
    onChange(String(next))
  }

  return (
    <div className="flex items-center gap-2">
      <button
        type="button"
        onClick={() => step(-1)}
        aria-label={t('sales.order.decrease', { item: item.name })}
        className="h-11 w-11 rounded-md border border-gray-300 bg-white text-xl font-semibold text-gray-700 hover:bg-gray-50"
      >
        −
      </button>
      <input
        type="number"
        inputMode="decimal"
        min="0"
        step="1"
        value={value}
        aria-label={t('sales.order.quantityFor', { item: item.name })}
        onChange={(event) => onChange(event.target.value)}
        className="h-11 w-20 rounded-md border-gray-300 text-center text-lg font-semibold shadow-sm focus:border-blue-500 focus:ring-blue-500"
      />
      <button
        type="button"
        onClick={() => step(1)}
        aria-label={t('sales.order.increase', { item: item.name })}
        className="h-11 w-11 rounded-md border border-gray-300 bg-white text-xl font-semibold text-gray-700 hover:bg-gray-50"
      >
        +
      </button>
    </div>
  )
}

export default function NewOrderPage() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { user } = useAuth()
  const owner = user?.username ?? ''

  const [search, setSearch] = useState('')
  const [customerId, setCustomerId] = useState<number | null>(null)
  const [quantities, setQuantities] = useState<Record<number, string>>({})
  const [notes, setNotes] = useState('')
  const [clientUuid, setClientUuid] = useState(() => crypto.randomUUID())
  const [error, setError] = useState<string | null>(null)
  const [submitted, setSubmitted] = useState<string | null>(null)
  const [queued, setQueued] = useState(false)
  const online = useOnline()

  const customers = useQuery({
    queryKey: ['customers', owner],
    queryFn: () => loadCustomers(owner),
    enabled: owner !== '',
    // Run the offline fallback instead of pausing when the browser is offline.
    networkMode: 'always'
  })
  const selectedCustomer: Customer | undefined = customers.data?.find(
    (row) => row.id === customerId
  )
  const catalogVersion = String(selectedCustomer?.price_list_id ?? 'default')
  const items = useQuery({
    queryKey: ['catalog', owner, customerId, catalogVersion],
    queryFn: () => loadCatalog(owner, customerId as number, catalogVersion),
    enabled: customerId !== null && owner !== '',
    networkMode: 'always'
  })

  const recents = readRecents()
  const filteredCustomers = useMemo(() => {
    const list = customers.data ?? []
    const term = search.trim().toLowerCase()
    const matches = term ? list.filter((row) => row.name.toLowerCase().includes(term)) : list
    return [...matches].sort((a, b) => {
      const aRecent = recents.indexOf(a.id)
      const bRecent = recents.indexOf(b.id)
      if (aRecent === -1 && bRecent === -1) return a.name.localeCompare(b.name)
      if (aRecent === -1) return 1
      if (bRecent === -1) return -1
      return aRecent - bRecent
    })
  }, [customers.data, search, recents])

  const selectedLines = (items.data ?? []).filter((item) => Number(quantities[item.id] ?? '0') > 0)

  const mutation = useMutation({
    // Without this React Query pauses the mutation while offline, so the
    // outbox would never be written and the order would wait for reconnect.
    networkMode: 'always',
    mutationFn: async (): Promise<{ queued: boolean; number?: string }> => {
      const payload: CreateOrderInput = {
        client_uuid: clientUuid,
        customer: customerId as number,
        notes,
        lines: selectedLines.map((item) => ({
          item: item.id,
          qty: quantities[item.id] ?? '0'
        }))
      }
      if (navigator.onLine) {
        try {
          const order = await createOrder(payload)
          return { queued: false, number: order.number }
        } catch (failure) {
          // A dropped connection is not a rejected order: keep it on the
          // device under the same client UUID and let the outbox retry.
          if (!isNetworkError(failure)) throw failure
        }
      }
      await enqueueOrder(payload, selectedCustomer?.name ?? '', owner)
      return { queued: true }
    },
    onSuccess: (outcome) => {
      setError(null)
      setQueued(outcome.queued)
      setSubmitted(outcome.queued ? null : (outcome.number ?? null))
      setQuantities({})
      setNotes('')
      setClientUuid(crypto.randomUUID())
      if (customerId !== null) rememberCustomer(customerId)
      queryClient.invalidateQueries({ queryKey: ['orders'] })
    },
    onError: (failure) => setError(apiErrorMessage(failure, t('sales.order.error')))
  })

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError(null)
    setSubmitted(null)
    setQueued(false)
    if (customerId === null || selectedLines.length === 0) {
      setError(t('sales.order.needCustomerAndItem'))
      return
    }
    mutation.mutate()
  }

  return (
    <div className="mx-auto max-w-2xl p-4 pb-24 sm:p-6">
      <h2 className="text-2xl font-semibold text-gray-800">{t('sales.order.title')}</h2>
      <p className="mt-1 text-sm text-gray-500">{t('sales.order.subtitle')}</p>

      {!online && (
        <p className="mt-3 rounded-md border border-amber-300 bg-amber-50 p-3 text-sm text-amber-800">
          {t('sales.order.offlineHint')}
        </p>
      )}
      {submitted && (
        <div role="status" className="mt-4 rounded-md border border-green-300 bg-green-50 p-3 text-sm text-green-800">
          {t('sales.order.submitted', { number: submitted })}{' '}
          <button
            type="button"
            onClick={() => navigate('/orders')}
            className="font-semibold underline"
          >
            {t('sales.order.viewOrders')}
          </button>
        </div>
      )}
      {queued && (
        <div role="status" className="mt-4 rounded-md border border-blue-300 bg-blue-50 p-3 text-sm text-blue-900">
          {t('sales.order.queued')}{' '}
          <button
            type="button"
            onClick={() => navigate('/orders')}
            className="font-semibold underline"
          >
            {t('sales.order.viewOrders')}
          </button>
        </div>
      )}
      {error && (
        <div role="alert" className="mt-4 rounded-md border border-red-300 bg-red-50 p-3 text-sm text-red-700">
          {error}
        </div>
      )}

      <form className="mt-6 space-y-6" onSubmit={handleSubmit}>
        <section className="space-y-3">
          <h3 className="text-lg font-semibold text-gray-800">{t('sales.order.customer')}</h3>
          <input
            type="search"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder={t('sales.order.searchCustomer')}
            aria-label={t('sales.order.searchCustomer')}
            className="block w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500"
          />
          {recents.length > 0 && (
            <p className="text-xs text-gray-500">{t('sales.order.recentsHint')}</p>
          )}
          <div className="grid gap-2">
            {customers.isLoading && (
              <LoadingPanel label={t('sales.loading')}>
                <SkeletonCardList count={2} />
              </LoadingPanel>
            )}
            {filteredCustomers.map((customer) => {
              const active = customer.id === customerId
              return (
                <button
                  key={customer.id}
                  type="button"
                  onClick={() => {
                    setCustomerId(customer.id)
                    setQuantities({})
                  }}
                  className={`flex min-h-[44px] items-center justify-between rounded-lg border px-4 py-3 text-left ${
                    active
                      ? 'border-blue-600 bg-blue-50 text-blue-900'
                      : 'border-gray-200 bg-white text-gray-800 hover:border-blue-300'
                  }`}
                >
                  <span className="font-medium">{customer.name}</span>
                  <span className="text-xs text-gray-500">
                    {t('sales.order.stateCode', { code: customer.state_code })}
                  </span>
                </button>
              )
            })}
            {customers.data && filteredCustomers.length === 0 && (
              <p className="text-sm text-gray-500">{t('sales.order.noCustomers')}</p>
            )}
          </div>
        </section>

        {selectedCustomer && (
          <section className="space-y-3">
            <h3 className="text-lg font-semibold text-gray-800">{t('sales.order.products')}</h3>
            {items.isLoading && (
              <LoadingPanel label={t('sales.loading')}>
                <SkeletonCardList count={3} />
              </LoadingPanel>
            )}
            {items.data && items.data.length === 0 && (
              <p className="text-sm text-gray-500">{t('sales.order.noProducts')}</p>
            )}
            <div className="divide-y divide-gray-200 rounded-lg border border-gray-200 bg-white">
              {(items.data ?? [])
                .filter((item) => item.price !== null)
                .map((item) => (
                  <div
                    key={item.id}
                    className="flex flex-col gap-3 p-4 sm:flex-row sm:items-center sm:justify-between"
                  >
                    <div>
                      <div className="text-lg font-medium text-gray-900">{item.name}</div>
                      <div className="text-sm text-gray-500">
                        {t('sales.order.priceEach', { price: formatMoney(item.price) })} ·{' '}
                        {t('sales.order.gst', { rate: item.gst_rate })}
                      </div>
                    </div>
                    <Stepper
                      item={item}
                      value={quantities[item.id] ?? '0'}
                      onChange={(value) =>
                        setQuantities((prev) => ({ ...prev, [item.id]: value }))
                      }
                    />
                  </div>
                ))}
            </div>
          </section>
        )}

        <section className="space-y-2">
          <label htmlFor="order-notes" className="block text-sm font-medium text-gray-700">
            {t('sales.order.notes')}
          </label>
          <textarea
            id="order-notes"
            rows={2}
            value={notes}
            onChange={(event) => setNotes(event.target.value)}
            className="block w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500"
          />
        </section>

        <button
          type="submit"
          disabled={mutation.isPending || selectedLines.length === 0}
          className="min-h-[44px] w-full rounded-md bg-blue-800 px-5 py-3 text-base font-semibold text-white hover:bg-blue-700 disabled:opacity-50"
        >
          {mutation.isPending ? '…' : t('sales.order.submit')}
        </button>
        <p className="text-center text-xs text-gray-500">{t('sales.order.totalHint')}</p>
      </form>
    </div>
  )
}
