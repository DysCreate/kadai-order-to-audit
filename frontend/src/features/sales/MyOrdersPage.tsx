import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { formatMoney } from '../../lib/money'
import { getSalesSummary, listOrders, type Order, type OrderState } from './salesApi'
import { orderTimeline } from './orderStatus'

const STATE_STYLES: Record<OrderState, string> = {
  SUBMITTED: 'bg-amber-100 text-amber-800',
  APPROVED: 'bg-blue-100 text-blue-800',
  REJECTED: 'bg-red-100 text-red-800',
  INVOICED: 'bg-indigo-100 text-indigo-800',
  DISPATCHED: 'bg-green-100 text-green-800'
}

function Timeline({ order }: { order: Order }) {
  const { t } = useTranslation()
  return (
    <ol className="flex flex-wrap items-center gap-2 text-xs">
      {orderTimeline(order.state).map((step) => (
        <li
          key={step.state}
          aria-current={step.current ? 'step' : undefined}
          className={`rounded-full border px-2 py-1 ${
            step.done
              ? 'border-blue-200 bg-blue-50 text-blue-800'
              : 'border-gray-200 bg-gray-50 text-gray-400'
          }`}
        >
          {t(`sales.states.${step.state}`)}
        </li>
      ))}
    </ol>
  )
}

export default function MyOrdersPage() {
  const { t } = useTranslation()
  const { data, isLoading, isError } = useQuery({
    queryKey: ['orders'],
    queryFn: () => listOrders()
  })
  const summary = useQuery({
    queryKey: ['sales-summary'],
    queryFn: () => getSalesSummary()
  })

  return (
    <div className="mx-auto max-w-3xl p-4 sm:p-6">
      <h2 className="text-2xl font-semibold text-gray-800">{t('sales.orders.title')}</h2>
      <p className="mt-1 text-sm text-gray-500">{t('sales.orders.subtitle')}</p>

      {isLoading && <p className="mt-6 text-gray-500">{t('sales.loading')}</p>}
      {isError && (
        <p role="alert" className="mt-6 text-red-700">
          {t('sales.orders.loadError')}
        </p>
      )}
      {summary.data && summary.data.length > 0 && (
        <section className="mt-6 rounded-lg border border-gray-200 bg-white p-4">
          <h3 className="text-lg font-semibold text-gray-800">
            {t('sales.orders.summaryTitle')}
          </h3>
          <p className="text-sm text-gray-500">{t('sales.orders.summarySubtitle')}</p>
          <ul className="mt-2 divide-y divide-gray-100 text-sm">
            {summary.data.map((row) => (
              <li key={row.customer_id} className="flex items-center justify-between py-2">
                <div>
                  <div className="font-medium text-gray-900">{row.customer_name}</div>
                  <div className="text-xs text-gray-500">
                    {t('sales.orders.summaryOrders', { count: row.order_count })}
                  </div>
                </div>
                <span className="tabular-nums font-medium text-gray-900">
                  {formatMoney(row.total_value)}
                </span>
              </li>
            ))}
          </ul>
        </section>
      )}

      {data && data.length === 0 && <p className="mt-6 text-gray-500">{t('sales.orders.empty')}</p>}

      {data && data.length > 0 && (
        <ul className="mt-6 space-y-3">
          {data.map((order) => (
            <li key={order.id} className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm">
              <div className="flex flex-wrap items-start justify-between gap-2">
                <div>
                  <div className="text-lg font-semibold text-gray-900">{order.number}</div>
                  <div className="text-sm text-gray-500">{order.customer_name}</div>
                </div>
                <div className="text-right">
                  <div className="text-lg font-semibold text-gray-900">
                    {formatMoney(order.total_value)}
                  </div>
                  <span
                    className={`inline-flex rounded-full px-3 py-1 text-sm font-medium ${STATE_STYLES[order.state]}`}
                  >
                    {t(`sales.states.${order.state}`)}
                  </span>
                </div>
              </div>

              <div className="mt-3">
                <Timeline order={order} />
              </div>

              {order.state === 'REJECTED' && order.rejection_reason && (
                <p className="mt-2 text-sm text-red-700">
                  {t('sales.orders.reason', { reason: order.rejection_reason })}
                </p>
              )}

              <ul className="mt-3 space-y-1 text-sm text-gray-700">
                {order.lines.map((line) => (
                  <li key={line.id} className="flex justify-between">
                    <span>
                      {line.item_name} × {line.qty} {line.uom}
                    </span>
                    <span className="tabular-nums">{formatMoney(line.line_value)}</span>
                  </li>
                ))}
              </ul>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
