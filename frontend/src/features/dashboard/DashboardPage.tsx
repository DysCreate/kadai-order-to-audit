import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { formatMoney } from '../../lib/money'
import { LoadingPanel, Skeleton, SkeletonTable } from '../../components/Skeleton'
import { getDashboard } from '../reports/reportsApi'

function Tile({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="rounded-lg border border-gray-200 bg-white p-4">
      <div className="text-sm text-gray-500">{label}</div>
      <div className="mt-1 text-2xl font-semibold tabular-nums text-gray-900">{value}</div>
      {hint && <div className="mt-1 text-xs text-gray-500">{hint}</div>}
    </div>
  )
}

export default function DashboardPage() {
  const { t } = useTranslation()
  const { data, isLoading, isError } = useQuery({
    queryKey: ['dashboard'],
    queryFn: getDashboard
  })

  return (
    <div className="p-4 sm:p-6">
      <h2 className="text-2xl font-semibold text-gray-800">{t('dashboard.title')}</h2>
      <p className="mt-1 text-sm text-gray-500">{t('dashboard.subtitle')}</p>

      {isLoading && (
        <LoadingPanel label={t('dashboard.loading')} className="mt-5">
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            {Array.from({ length: 4 }, (_, index) => (
              <div key={index} className="rounded-lg border border-gray-200 bg-white p-4">
                <Skeleton className="h-4 w-24" />
                <Skeleton className="mt-3 h-8 w-28" />
                <Skeleton className="mt-2 h-3 w-32 max-w-full" />
              </div>
            ))}
          </div>
          <div className="mt-6 grid gap-4 lg:grid-cols-2">
            {Array.from({ length: 2 }, (_, index) => (
              <div
                key={index}
                className="rounded-lg border border-gray-200 bg-white p-4"
              >
                <Skeleton className="h-5 w-40" />
                <Skeleton className="mt-4 h-9 w-32" />
                <Skeleton className="mt-3 h-4 w-full" />
                <Skeleton className="mt-2 h-4 w-2/3" />
              </div>
            ))}
          </div>
          <div className="mt-6">
            <Skeleton className="h-5 w-32" />
            <div className="mt-2">
              <SkeletonTable rows={6} columns={5} />
            </div>
          </div>
        </LoadingPanel>
      )}
      {isError && (
        <p role="alert" className="mt-6 text-red-700">
          {t('dashboard.loadError')}
        </p>
      )}

      {data && (
        <>
          <section className="mt-5 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <Tile
              label={t('dashboard.todayOrders')}
              value={String(data.today_orders.count)}
              hint={formatMoney(data.today_orders.value)}
            />
            <Tile
              label={t('dashboard.openOrders')}
              value={String(data.open_orders.count)}
              hint={t('dashboard.openHint', {
                submitted: data.open_orders.submitted,
                approved: data.open_orders.approved
              })}
            />
            <Tile
              label={t('dashboard.outstanding')}
              value={formatMoney(data.outstanding_dues.amount)}
              hint={t('dashboard.customersDue', { count: data.outstanding_dues.customers })}
            />
            <Tile
              label={t('dashboard.reorderLines')}
              value={String(data.reorder_count)}
              hint={t('dashboard.reorderHint')}
            />
          </section>

          <section className="mt-6 grid gap-4 lg:grid-cols-2">
            <div className="rounded-lg border border-gray-200 bg-white p-4">
              <h3 className="text-lg font-semibold text-gray-800">
                {t('dashboard.costPerPacket')}
              </h3>
              {data.cost_per_packet ? (
                <div className="mt-2 text-sm text-gray-700">
                  <div className="text-3xl font-semibold tabular-nums text-gray-900">
                    {formatMoney(data.cost_per_packet.cost_per_packet)}
                  </div>
                  <div className="mt-1">{data.cost_per_packet.product}</div>
                  <div className="mt-1 text-gray-500">
                    {t('dashboard.margin', {
                      margin: formatMoney(data.cost_per_packet.margin_per_packet),
                      pct: data.cost_per_packet.margin_pct ?? '—'
                    })}
                  </div>
                </div>
              ) : (
                <p className="mt-2 text-sm text-gray-500">{t('dashboard.noCost')}</p>
              )}
            </div>

            <div className="rounded-lg border border-gray-200 bg-white p-4">
              <h3 className="text-lg font-semibold text-gray-800">
                {t('dashboard.varianceAlerts')}
              </h3>
              {data.variance_alerts.length === 0 && (
                <p className="mt-2 text-sm text-gray-500">{t('dashboard.noAlerts')}</p>
              )}
              <ul className="mt-2 space-y-2 text-sm">
                {data.variance_alerts.map((alert) => (
                  <li
                    key={`${alert.run_id}-${alert.item_name}-${alert.kind}`}
                    className="flex items-center justify-between gap-2 rounded border border-amber-200 bg-amber-50 px-3 py-2"
                  >
                    <span className="text-gray-900">
                      {alert.item_name} · {alert.product}
                    </span>
                    <span className="tabular-nums text-amber-900">
                      {alert.variance_pct} ({alert.direction})
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          </section>

          <section className="mt-6">
            <h3 className="text-lg font-semibold text-gray-800">{t('dashboard.stock')}</h3>
            <div className="mt-2 overflow-x-auto rounded-lg border border-gray-200 bg-white">
              <table className="min-w-full divide-y divide-gray-200 text-sm">
                <thead className="bg-gray-50">
                  <tr>
                    <th className="px-3 py-2 text-left font-semibold text-gray-600">
                      {t('dashboard.item')}
                    </th>
                    <th className="px-3 py-2 text-left font-semibold text-gray-600">
                      {t('dashboard.type')}
                    </th>
                    <th className="px-3 py-2 text-right font-semibold text-gray-600">
                      {t('dashboard.qty')}
                    </th>
                    <th className="px-3 py-2 text-right font-semibold text-gray-600">
                      {t('dashboard.value')}
                    </th>
                    <th className="px-3 py-2 text-left font-semibold text-gray-600">
                      {t('dashboard.status')}
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {data.stock.map((row) => (
                    <tr key={row.item_id}>
                      <td className="px-3 py-2 font-medium text-gray-900">{row.item_name}</td>
                      <td className="px-3 py-2 text-gray-600">{row.item_type}</td>
                      <td className="px-3 py-2 text-right tabular-nums text-gray-700">
                        {row.qty} {row.uom}
                      </td>
                      <td className="px-3 py-2 text-right tabular-nums text-gray-700">
                        {formatMoney(row.value)}
                      </td>
                      <td className="px-3 py-2">
                        {row.reorder ? (
                          <span className="inline-flex rounded-full bg-red-100 px-2 py-1 text-xs font-medium text-red-800">
                            {t('dashboard.reorder', { qty: row.reorder_qty })}
                          </span>
                        ) : (
                          <span className="inline-flex rounded-full bg-green-100 px-2 py-1 text-xs font-medium text-green-800">
                            {t('dashboard.ok')}
                          </span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        </>
      )}
    </div>
  )
}
