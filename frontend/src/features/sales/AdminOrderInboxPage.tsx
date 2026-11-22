import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router-dom'
import { apiErrorMessage } from '../../lib/apiError'
import { formatMoney } from '../../lib/money'
import { LoadingPanel, SkeletonCardList, SkeletonText } from '../../components/Skeleton'
import {
  approveOrder,
  createInvoice,
  editOrderLine,
  getOrderCoverage,
  listOrders,
  rejectOrder,
  type Order,
  type OrderState
} from './salesApi'
import { canApprove, canInvoice } from './orderStatus'

const FILTERS: (OrderState | 'ALL')[] = ['SUBMITTED', 'APPROVED', 'ALL']

const STATE_STYLES: Record<OrderState, string> = {
  SUBMITTED: 'bg-amber-100 text-amber-800',
  APPROVED: 'bg-blue-100 text-blue-800',
  REJECTED: 'bg-red-100 text-red-800',
  INVOICED: 'bg-indigo-100 text-indigo-800',
  DISPATCHED: 'bg-green-100 text-green-800'
}

export default function AdminOrderInboxPage() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const queryClient = useQueryClient()

  const [filter, setFilter] = useState<OrderState | 'ALL'>('SUBMITTED')
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [edits, setEdits] = useState<Record<number, { qty: string; price: string }>>({})
  const [rejectReason, setRejectReason] = useState('')
  const [error, setError] = useState<string | null>(null)

  const orders = useQuery({
    queryKey: ['orders', filter],
    queryFn: () => listOrders(filter === 'ALL' ? {} : { state: filter })
  })

  const selected: Order | null = orders.data?.find((order) => order.id === selectedId) ?? null

  const coverage = useQuery({
    queryKey: ['coverage', selectedId],
    queryFn: () => getOrderCoverage(selectedId as number),
    enabled: selectedId !== null
  })

  useEffect(() => {
    if (!selected) return
    const next: Record<number, { qty: string; price: string }> = {}
    for (const line of selected.lines) {
      next[line.id] = { qty: line.qty, price: line.unit_price }
    }
    setEdits(next)
    setRejectReason('')
  }, [selected?.id, selected?.updated_at]) // eslint-disable-line react-hooks/exhaustive-deps

  const refresh = (order: Order) => {
    setError(null)
    queryClient.invalidateQueries({ queryKey: ['orders'] })
    queryClient.invalidateQueries({ queryKey: ['coverage', order.id] })
  }
  const onFailure = (fallback: string) => (failure: unknown) =>
    setError(apiErrorMessage(failure, fallback))

  const editMutation = useMutation({
    mutationFn: (lineId: number) =>
      editOrderLine(selectedId as number, lineId, {
        qty: edits[lineId]?.qty,
        unit_price: edits[lineId]?.price
      }),
    onSuccess: refresh,
    onError: onFailure(t('sales.inbox.editError'))
  })

  const approveMutation = useMutation({
    mutationFn: () => approveOrder(selectedId as number),
    onSuccess: refresh,
    onError: onFailure(t('sales.inbox.approveError'))
  })

  const rejectMutation = useMutation({
    mutationFn: () => rejectOrder(selectedId as number, rejectReason),
    onSuccess: refresh,
    onError: onFailure(t('sales.inbox.rejectError'))
  })

  const invoiceMutation = useMutation({
    mutationFn: () => createInvoice(selectedId as number),
    onSuccess: (invoice) => {
      setError(null)
      queryClient.invalidateQueries({ queryKey: ['orders'] })
      navigate(`/invoices/${invoice.id}`)
    },
    onError: onFailure(t('sales.inbox.invoiceError'))
  })

  const coverageByLine = new Map((coverage.data?.lines ?? []).map((row) => [row.line_id, row]))

  return (
    <div className="p-4 sm:p-6">
      <h2 className="text-2xl font-semibold text-gray-800">{t('sales.inbox.title')}</h2>
      <p className="mt-1 text-sm text-gray-500">{t('sales.inbox.subtitle')}</p>

      <div className="mt-4 flex flex-wrap gap-2">
        {FILTERS.map((value) => (
          <button
            key={value}
            type="button"
            onClick={() => {
              setFilter(value)
              setSelectedId(null)
            }}
            className={`min-h-[44px] rounded-full border px-4 py-2 text-sm font-medium ${
              filter === value
                ? 'border-blue-700 bg-blue-800 text-white'
                : 'border-gray-300 bg-white text-gray-700 hover:border-blue-400'
            }`}
          >
            {value === 'ALL' ? t('sales.inbox.all') : t(`sales.states.${value}`)}
          </button>
        ))}
      </div>

      {error && (
        <div role="alert" className="mt-4 rounded-md border border-red-300 bg-red-50 p-3 text-sm text-red-700">
          {error}
        </div>
      )}

      <div className="mt-5 grid gap-5 xl:grid-cols-2">
        <ul className="space-y-3">
          {orders.isLoading && (
            <li>
              <LoadingPanel label={t('sales.loading')}>
                <SkeletonCardList count={3} />
              </LoadingPanel>
            </li>
          )}
          {orders.data && orders.data.length === 0 && (
            <li className="text-gray-500">{t('sales.inbox.empty')}</li>
          )}
          {(orders.data ?? []).map((order) => (
            <li key={order.id}>
              <button
                type="button"
                onClick={() => setSelectedId(order.id)}
                className={`w-full rounded-lg border p-4 text-left shadow-sm ${
                  selectedId === order.id
                    ? 'border-blue-600 bg-blue-50'
                    : 'border-gray-200 bg-white hover:border-blue-300'
                }`}
              >
                <div className="flex items-start justify-between gap-2">
                  <div>
                    <div className="font-semibold text-gray-900">{order.number}</div>
                    <div className="text-sm text-gray-500">
                      {order.customer_name} · {order.salesman_username}
                    </div>
                  </div>
                  <span
                    className={`inline-flex rounded-full px-3 py-1 text-xs font-medium ${STATE_STYLES[order.state]}`}
                  >
                    {t(`sales.states.${order.state}`)}
                  </span>
                </div>
                <div className="mt-2 text-sm text-gray-700">
                  {order.lines.map((line) => `${line.item_name} × ${line.qty}`).join(', ')}
                </div>
                <div className="mt-1 text-sm font-medium text-gray-900">
                  {formatMoney(order.total_value)}
                </div>
              </button>
            </li>
          ))}
        </ul>

        {selected && (
          <section className="space-y-4 rounded-lg border border-gray-200 bg-white p-4">
            <header>
              <h3 className="text-lg font-semibold text-gray-900">{selected.number}</h3>
              <p className="text-sm text-gray-500">
                {selected.customer_name} · {t('sales.inbox.stateCode', { code: selected.customer_state_code })}
              </p>
            </header>

            <div className="overflow-x-auto">
              <table className="min-w-full divide-y divide-gray-200 text-sm">
                <thead className="bg-gray-50">
                  <tr>
                    <th className="px-2 py-2 text-left font-semibold text-gray-600">
                      {t('sales.inbox.item')}
                    </th>
                    <th className="px-2 py-2 text-right font-semibold text-gray-600">
                      {t('sales.inbox.ordered')}
                    </th>
                    <th className="px-2 py-2 text-right font-semibold text-gray-600">
                      {t('sales.inbox.available')}
                    </th>
                    <th className="px-2 py-2 text-right font-semibold text-gray-600">
                      {t('sales.inbox.qty')}
                    </th>
                    <th className="px-2 py-2 text-right font-semibold text-gray-600">
                      {t('sales.inbox.price')}
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {selected.lines.map((line) => {
                    const cover = coverageByLine.get(line.id)
                    const shortage = cover ? Number(cover.shortage_qty) : 0
                    return (
                      <tr key={line.id}>
                        <td className="px-2 py-2">
                          <div className="font-medium text-gray-900">{line.item_name}</div>
                          <div className="text-xs text-gray-500">
                            {t('sales.inbox.plan', { qty: line.qty, uom: line.uom })}
                          </div>
                          {cover && (
                            <span
                              className={`mt-1 inline-flex rounded-full px-2 py-0.5 text-xs font-medium ${
                                shortage > 0
                                  ? 'bg-red-100 text-red-800'
                                  : 'bg-green-100 text-green-800'
                              }`}
                            >
                              {shortage > 0
                                ? t('sales.inbox.shortage', { qty: cover.shortage_qty })
                                : t('sales.inbox.covered', { qty: cover.available_qty })}
                            </span>
                          )}
                        </td>
                        <td className="px-2 py-2 text-right tabular-nums text-gray-700">
                          {line.qty}
                        </td>
                        <td className="px-2 py-2 text-right tabular-nums text-gray-700">
                          {cover ? cover.available_qty : '—'}
                        </td>
                        <td className="px-2 py-2 text-right">
                          <input
                            type="number"
                            min="0.001"
                            step="0.001"
                            value={edits[line.id]?.qty ?? line.qty}
                            disabled={!canApprove(selected.state)}
                            aria-label={t('sales.inbox.editQtyFor', { item: line.item_name })}
                            onChange={(event) =>
                              setEdits((prev) => ({
                                ...prev,
                                [line.id]: {
                                  qty: event.target.value,
                                  price: prev[line.id]?.price ?? line.unit_price
                                }
                              }))
                            }
                            className="h-11 w-24 rounded-md border-gray-300 text-right tabular-nums shadow-sm focus:border-blue-500 focus:ring-blue-500 disabled:bg-gray-100"
                          />
                        </td>
                        <td className="px-2 py-2 text-right">
                          <input
                            type="number"
                            min="0"
                            step="0.01"
                            value={edits[line.id]?.price ?? line.unit_price}
                            disabled={!canApprove(selected.state)}
                            aria-label={t('sales.inbox.editPriceFor', { item: line.item_name })}
                            onChange={(event) =>
                              setEdits((prev) => ({
                                ...prev,
                                [line.id]: {
                                  qty: prev[line.id]?.qty ?? line.qty,
                                  price: event.target.value
                                }
                              }))
                            }
                            className="h-11 w-24 rounded-md border-gray-300 text-right tabular-nums shadow-sm focus:border-blue-500 focus:ring-blue-500 disabled:bg-gray-100"
                          />
                          {canApprove(selected.state) && (
                            <button
                              type="button"
                              onClick={() => editMutation.mutate(line.id)}
                              disabled={editMutation.isPending}
                              className="mt-1 block w-full rounded border border-gray-300 px-2 py-1 text-xs font-medium text-gray-700 hover:bg-gray-50"
                            >
                              {t('sales.inbox.saveLine')}
                            </button>
                          )}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>

            {coverage.isLoading && (
              <LoadingPanel label={t('common.loading')}>
                <SkeletonText lines={2} />
              </LoadingPanel>
            )}
            {coverage.data && (
              <div className="rounded-md bg-gray-50 p-3 text-sm">
                <div className="font-medium text-gray-800">
                  {t('sales.inbox.taxPreview', {
                    total: formatMoney(coverage.data.tax_preview.total)
                  })}
                </div>
                <div className="mt-1 text-gray-600">
                  {t('sales.inbox.taxable', { value: formatMoney(coverage.data.tax_preview.taxable_total) })}{' '}
                  {coverage.data.is_interstate
                    ? t('sales.inbox.igst', {
                        value: formatMoney(coverage.data.tax_preview.igst_total)
                      })
                    : t('sales.inbox.cgstSgst', {
                        cgst: formatMoney(coverage.data.tax_preview.cgst_total),
                        sgst: formatMoney(coverage.data.tax_preview.sgst_total)
                      })}
                </div>
                {Number(coverage.data.total_shortage_qty) > 0 && (
                  <div className="mt-2 rounded border border-amber-300 bg-amber-50 p-2 text-amber-800">
                    {t('sales.inbox.shortageHint', {
                      qty: coverage.data.total_shortage_qty
                    })}
                  </div>
                )}
              </div>
            )}

            {canApprove(selected.state) && (
              <div className="space-y-3 border-t border-gray-200 pt-3">
                <button
                  type="button"
                  onClick={() => approveMutation.mutate()}
                  disabled={approveMutation.isPending}
                  className="min-h-[44px] w-full rounded-md bg-blue-800 px-4 py-2 font-semibold text-white hover:bg-blue-700 disabled:opacity-50"
                >
                  {t('sales.inbox.approve')}
                </button>
                <div className="flex flex-col gap-2 sm:flex-row">
                  <input
                    type="text"
                    value={rejectReason}
                    onChange={(event) => setRejectReason(event.target.value)}
                    placeholder={t('sales.inbox.rejectReason')}
                    aria-label={t('sales.inbox.rejectReason')}
                    className="min-h-[44px] flex-1 rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500"
                  />
                  <button
                    type="button"
                    onClick={() => rejectMutation.mutate()}
                    disabled={rejectMutation.isPending || rejectReason.trim() === ''}
                    className="min-h-[44px] rounded-md border border-red-300 bg-white px-4 py-2 font-medium text-red-700 hover:bg-red-50 disabled:opacity-50"
                  >
                    {t('sales.inbox.reject')}
                  </button>
                </div>
              </div>
            )}

            {canInvoice(selected.state) && (
              <button
                type="button"
                onClick={() => invoiceMutation.mutate()}
                disabled={invoiceMutation.isPending}
                className="min-h-[44px] w-full rounded-md bg-blue-800 px-4 py-2 font-semibold text-white hover:bg-blue-700 disabled:opacity-50"
              >
                {t('sales.inbox.invoice')}
              </button>
            )}

            {selected.state === 'REJECTED' && selected.rejection_reason && (
              <p className="text-sm text-red-700">
                {t('sales.orders.reason', { reason: selected.rejection_reason })}
              </p>
            )}
          </section>
        )}
      </div>
    </div>
  )
}
