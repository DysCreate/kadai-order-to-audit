import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import { formatMoney } from '../../lib/money'
import { LoadingPanel, Skeleton, SkeletonCardList } from '../../components/Skeleton'
import { getSalesSummary, listInvoices, listOrders, type OrderState } from '../sales/salesApi'

const STATE_STYLES: Record<OrderState, string> = {
  SUBMITTED: 'bg-amber-100 text-amber-800',
  APPROVED: 'bg-blue-100 text-blue-800',
  REJECTED: 'bg-red-100 text-red-800',
  INVOICED: 'bg-indigo-100 text-indigo-800',
  DISPATCHED: 'bg-green-100 text-green-800'
}

function Tile({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="rounded-lg border border-gray-200 bg-white p-4">
      <div className="text-sm text-gray-500">{label}</div>
      <div className="mt-1 text-2xl font-semibold tabular-nums text-gray-900">{value}</div>
      {hint && <div className="mt-1 text-xs text-gray-500">{hint}</div>}
    </div>
  )
}

/**
 * The salesman's own day-at-a-glance.
 *
 * The server scopes every order and invoice query to the signed-in salesman, so
 * this screen never sees another salesman's book. Counts are computed from the
 * returned rows; all money comes from the server as strings and is only
 * formatted here — the frontend never does money arithmetic.
 */
export default function SalesmanDashboardPage() {
  const { t } = useTranslation()
  const orders = useQuery({ queryKey: ['orders'], queryFn: () => listOrders() })
  const summary = useQuery({ queryKey: ['sales-summary'], queryFn: () => getSalesSummary() })
  const invoices = useQuery({ queryKey: ['invoices'], queryFn: listInvoices })

  const isLoading = orders.isLoading || summary.isLoading || invoices.isLoading
  const isError = orders.isError || summary.isError || invoices.isError

  const orderRows = orders.data ?? []
  const invoiceRows = invoices.data ?? []
  const summaryRows = summary.data ?? []

  const openOrders = orderRows.filter(
    (order) => order.state === 'SUBMITTED' || order.state === 'APPROVED'
  )
  const awaitingApproval = orderRows.filter((order) => order.state === 'SUBMITTED')
  const readyToDispatch = orderRows.filter((order) => order.state === 'APPROVED')
  const cancelledInvoices = invoiceRows.filter((invoice) => invoice.is_cancelled)

  return (
    <div className="p-4 sm:p-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-2xl font-semibold text-gray-800">{t('dashboard.salesman.title')}</h2>
          <p className="mt-1 text-sm text-gray-500">{t('dashboard.salesman.subtitle')}</p>
        </div>
        <Link
          to="/orders/new"
          className="inline-flex min-h-[44px] items-center rounded-md bg-blue-900 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-800"
        >
          {t('dashboard.salesman.newOrder')}
        </Link>
      </div>

      {isLoading && (
        <LoadingPanel label={t('dashboard.loading')} className="mt-5">
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            {Array.from({ length: 4 }, (_, index) => (
              <div key={index} className="rounded-lg border border-gray-200 bg-white p-4">
                <Skeleton className="h-4 w-24" />
                <Skeleton className="mt-3 h-8 w-16" />
                <Skeleton className="mt-2 h-3 w-28 max-w-full" />
              </div>
            ))}
          </div>
          <div className="mt-6">
            <SkeletonCardList count={3} />
          </div>
        </LoadingPanel>
      )}
      {isError && (
        <p role="alert" className="mt-6 text-red-700">
          {t('dashboard.salesman.loadError')}
        </p>
      )}

      {!isLoading && !isError && (
        <>
          <section className="mt-5 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <Tile
              label={t('dashboard.salesman.openOrders')}
              value={String(openOrders.length)}
              hint={t('dashboard.salesman.openHint')}
            />
            <Tile
              label={t('dashboard.salesman.awaitingApproval')}
              value={String(awaitingApproval.length)}
              hint={t('dashboard.salesman.awaitingApprovalHint')}
            />
            <Tile
              label={t('dashboard.salesman.readyToDispatch')}
              value={String(readyToDispatch.length)}
              hint={t('dashboard.salesman.readyToDispatchHint')}
            />
            <Tile
              label={t('dashboard.salesman.invoices')}
              value={String(invoiceRows.length)}
              hint={t('dashboard.salesman.cancelledHint', { count: cancelledInvoices.length })}
            />
          </section>

          <section className="mt-6 grid gap-4 lg:grid-cols-2">
            <div className="rounded-lg border border-gray-200 bg-white p-4">
              <h3 className="text-lg font-semibold text-gray-800">
                {t('dashboard.salesman.monthTitle')}
              </h3>
              <p className="text-sm text-gray-500">{t('dashboard.salesman.monthSubtitle')}</p>
              {summaryRows.length === 0 ? (
                <p className="mt-2 text-sm text-gray-500">{t('dashboard.salesman.monthEmpty')}</p>
              ) : (
                <ul className="mt-2 divide-y divide-gray-100 text-sm">
                  {summaryRows.map((row) => (
                    <li
                      key={row.customer_id}
                      className="flex items-center justify-between gap-3 py-2"
                    >
                      <div>
                        <div className="font-medium text-gray-900">{row.customer_name}</div>
                        <div className="text-xs text-gray-500">
                          {t('dashboard.salesman.customerOrders', { count: row.order_count })}
                        </div>
                      </div>
                      <span className="tabular-nums font-medium text-gray-900">
                        {formatMoney(row.total_value)}
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </div>

            <div className="rounded-lg border border-gray-200 bg-white p-4">
              <div className="flex items-center justify-between gap-3">
                <h3 className="text-lg font-semibold text-gray-800">
                  {t('dashboard.salesman.recentInvoices')}
                </h3>
                <Link to="/invoices" className="text-sm font-medium text-blue-800 hover:underline">
                  {t('dashboard.salesman.viewInvoices')}
                </Link>
              </div>
              {invoiceRows.length === 0 ? (
                <p className="mt-2 text-sm text-gray-500">
                  {t('dashboard.salesman.recentInvoicesEmpty')}
                </p>
              ) : (
                <ul className="mt-2 divide-y divide-gray-100 text-sm">
                  {invoiceRows.slice(0, 5).map((invoice) => (
                    <li key={invoice.id}>
                      <Link
                        to={`/invoices/${invoice.id}`}
                        className="flex items-center justify-between gap-3 py-2 hover:text-blue-800"
                      >
                        <div className="min-w-0">
                          <div className="truncate font-medium text-gray-900">{invoice.number}</div>
                          <div className="truncate text-xs text-gray-500">
                            {invoice.customer_name} · {invoice.invoice_date}
                          </div>
                        </div>
                        <div className="text-right">
                          <div className="tabular-nums font-medium text-gray-900">
                            {formatMoney(invoice.total)}
                          </div>
                          {invoice.is_cancelled && (
                            <div className="text-xs font-medium text-red-700">
                              {t('sales.invoices.cancelled')}
                            </div>
                          )}
                        </div>
                      </Link>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </section>

          <section className="mt-6">
            <div className="flex items-center justify-between gap-3">
              <h3 className="text-lg font-semibold text-gray-800">
                {t('dashboard.salesman.recentOrders')}
              </h3>
              <Link to="/orders" className="text-sm font-medium text-blue-800 hover:underline">
                {t('dashboard.salesman.viewOrders')}
              </Link>
            </div>
            {orderRows.length === 0 ? (
              <p className="mt-2 text-sm text-gray-500">
                {t('dashboard.salesman.recentOrdersEmpty')}
              </p>
            ) : (
              <ul className="mt-2 space-y-2">
                {orderRows.slice(0, 5).map((order) => (
                  <li
                    key={order.id}
                    className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-gray-200 bg-white px-4 py-3"
                  >
                    <div className="min-w-0">
                      <div className="font-semibold text-gray-900">{order.number}</div>
                      <div className="truncate text-sm text-gray-500">
                        {order.customer_name} · {order.created_at.slice(0, 10)}
                      </div>
                    </div>
                    <div className="flex items-center gap-3">
                      <span className="tabular-nums font-semibold text-gray-900">
                        {formatMoney(order.total_value)}
                      </span>
                      <span
                        className={`inline-flex rounded-full px-3 py-1 text-xs font-medium ${STATE_STYLES[order.state]}`}
                      >
                        {t(`sales.states.${order.state}`)}
                      </span>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </>
      )}
    </div>
  )
}
