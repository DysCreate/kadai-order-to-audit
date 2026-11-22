import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis
} from 'recharts'
import { formatMoney } from '../../lib/money'
import { SkeletonText } from '../../components/Skeleton'
import { getProductLeakage, getRunReportCard, type BridgeStep } from './productionApi'

const STEP_COLOURS: Record<BridgeStep['key'], string> = {
  standard_material: '#1d4ed8',
  yield_shortfall: '#dc2626',
  price_usage: '#d97706',
  overhead: '#7c3aed'
}

function impactClass(value: string): string {
  const amount = Number(value)
  if (amount > 0) return 'text-red-700'
  if (amount < 0) return 'text-green-700'
  return 'text-gray-700'
}

function bridgeRows(steps: BridgeStep[]) {
  return steps.map((step, index) => {
    const previous = index === 0 ? 0 : Number(steps[index - 1].cumulative)
    const cumulative = Number(step.cumulative)
    return {
      key: step.key,
      label: step.label,
      base: Math.min(previous, cumulative),
      height: Math.abs(cumulative - previous),
      cumulative,
      amount: Number(step.amount)
    }
  })
}

export default function ReportCardPanel({ runId, productId }: { runId: number; productId: number }) {
  const { t } = useTranslation()
  const card = useQuery({
    queryKey: ['report-card', runId],
    queryFn: () => getRunReportCard(runId)
  })
  const trends = useQuery({
    queryKey: ['leakage-trends', productId],
    queryFn: () => getProductLeakage(productId)
  })

  if (card.isLoading) return <SkeletonText lines={4} />
  if (card.isError || !card.data) {
    return (
      <p role="alert" className="text-red-700">
        {t('production.leakage.loadError')}
      </p>
    )
  }

  const data = card.data
  const rows = bridgeRows(data.bridge)

  return (
    <section className="mt-8 space-y-6">
      <div>
        <h3 className="text-lg font-semibold text-gray-800">{t('production.leakage.title')}</h3>
        <p className="text-sm text-gray-500">{t('production.leakage.subtitle')}</p>
      </div>

      <div className="overflow-x-auto rounded-lg border border-gray-200 bg-white">
        <table className="min-w-full divide-y divide-gray-200 text-sm">
          <thead className="bg-gray-50">
            <tr>
              <th className="px-3 py-2 text-left font-semibold text-gray-600">
                {t('production.leakage.input')}
              </th>
              <th className="px-3 py-2 text-right font-semibold text-gray-600">
                {t('production.leakage.standard')}
              </th>
              <th className="px-3 py-2 text-right font-semibold text-gray-600">
                {t('production.leakage.actual')}
              </th>
              <th className="px-3 py-2 text-right font-semibold text-gray-600">
                {t('production.leakage.priceImpact')}
              </th>
              <th className="px-3 py-2 text-right font-semibold text-gray-600">
                {t('production.leakage.usageImpact')}
              </th>
              <th className="px-3 py-2 text-right font-semibold text-gray-600">
                {t('production.leakage.impact')}
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {data.lines.map((line) => (
              <tr key={line.item_id}>
                <td className="px-3 py-2">
                  <div className="font-medium text-gray-900">{line.item_name}</div>
                  <div className="text-xs text-gray-500">
                    {line.planned_qty} → {line.actual_qty} · {t('production.leakage.rate', {
                      standard: line.standard_rate,
                      actual: line.actual_rate
                    })}
                  </div>
                </td>
                <td className="px-3 py-2 text-right tabular-nums text-gray-700">
                  {formatMoney(line.standard_value)}
                </td>
                <td className="px-3 py-2 text-right tabular-nums text-gray-700">
                  {formatMoney(line.actual_value)}
                </td>
                <td className="px-3 py-2 text-right tabular-nums text-gray-700">
                  {formatMoney(line.price_impact)}
                </td>
                <td className="px-3 py-2 text-right tabular-nums text-gray-700">
                  {formatMoney(line.usage_impact)}
                </td>
                <td
                  className={`px-3 py-2 text-right font-medium tabular-nums ${impactClass(line.total_impact)}`}
                >
                  {formatMoney(line.total_impact)}
                </td>
              </tr>
            ))}
            <tr className="bg-gray-50 font-semibold">
              <td className="px-3 py-2 text-gray-900">{t('production.leakage.materials')}</td>
              <td className="px-3 py-2 text-right tabular-nums text-gray-900">
                {formatMoney(data.standard_materials)}
              </td>
              <td className="px-3 py-2 text-right tabular-nums text-gray-900">
                {formatMoney(data.actual_materials)}
              </td>
              <td className="px-3 py-2 text-right tabular-nums text-gray-900">
                {formatMoney(data.price_impact)}
              </td>
              <td className="px-3 py-2 text-right tabular-nums text-gray-900">
                {formatMoney(data.usage_impact)}
              </td>
              <td className="px-3 py-2 text-right tabular-nums text-gray-900">
                {formatMoney(data.material_impact)}
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <div className="rounded-lg border border-gray-200 bg-white p-4">
          <h4 className="font-semibold text-gray-800">{t('production.leakage.bridgeTitle')}</h4>
          <div className="mt-3 h-56">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={rows} margin={{ top: 8, right: 8, bottom: 8, left: 0 }}>
                <CartesianGrid strokeDasharray="3 3" vertical={false} />
                <XAxis dataKey="label" tick={{ fontSize: 10 }} interval={0} />
                <YAxis tick={{ fontSize: 10 }} width={40} />
                <Tooltip formatter={(value) => formatMoney(String(value))} />
                <Bar dataKey="base" stackId="bridge" fill="transparent" isAnimationActive={false} />
                <Bar dataKey="height" stackId="bridge" isAnimationActive={false}>
                  {rows.map((row) => (
                    <Cell key={row.key} fill={STEP_COLOURS[row.key]} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
          <dl className="mt-3 grid grid-cols-2 gap-2 text-sm">
            <dt className="text-gray-500">{t('production.leakage.actualMaterialPerPacket')}</dt>
            <dd className="text-right tabular-nums text-gray-900">
              {formatMoney(data.actual_material_per_packet)}
            </dd>
            <dt className="text-gray-500">{t('production.leakage.overheadPerPacket')}</dt>
            <dd className="text-right tabular-nums text-gray-900">
              {formatMoney(data.overhead_per_packet)}
            </dd>
            <dt className="font-semibold text-gray-700">{t('production.leakage.costPerPacket')}</dt>
            <dd className="text-right font-semibold tabular-nums text-gray-900">
              {formatMoney(data.cost_per_packet)}
            </dd>
          </dl>
        </div>

        <div className="rounded-lg border border-gray-200 bg-white p-4">
          <h4 className="font-semibold text-gray-800">{t('production.leakage.yieldGapTitle')}</h4>
          <p className="mt-2 text-3xl font-semibold tabular-nums text-gray-900">
            {data.yield_gap.gap_packets}
          </p>
          <p className="mt-1 text-sm text-gray-600">
            {t('production.leakage.yieldGapText', {
              gap: data.yield_gap.gap_packets,
              damaged: data.yield_gap.damaged_packets,
              unexplained: data.yield_gap.unexplained_packets
            })}
          </p>
          <div className="mt-3 flex gap-3 text-sm">
            <div className="flex-1 rounded border border-amber-200 bg-amber-50 p-2">
              <div className="text-amber-800">{t('production.leakage.recordedDamage')}</div>
              <div className="text-lg font-semibold tabular-nums text-amber-900">
                {data.yield_gap.damaged_packets}
              </div>
            </div>
            <div className="flex-1 rounded border border-red-200 bg-red-50 p-2">
              <div className="text-red-800">{t('production.leakage.unexplained')}</div>
              <div className="text-lg font-semibold tabular-nums text-red-900">
                {data.yield_gap.unexplained_packets}
              </div>
            </div>
          </div>
        </div>
      </div>

      <div className="rounded-lg border border-gray-200 bg-white p-4">
        <h4 className="font-semibold text-gray-800">{t('production.leakage.trendsTitle')}</h4>
        <p className="text-sm text-gray-500">{t('production.leakage.trendsHint')}</p>
        {trends.isLoading && <SkeletonText lines={2} />}
        {trends.data && (
          <>
            {trends.data.drift_alerts.length > 0 && (
              <ul className="mt-2 space-y-1">
                {trends.data.drift_alerts.map((alert) => (
                  <li
                    key={alert.item_name}
                    className="rounded border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-900"
                  >
                    {t('production.leakage.drift', {
                      item: alert.item_name,
                      runs: alert.consecutive_runs,
                      pct: alert.latest_variance_pct
                    })}
                  </li>
                ))}
              </ul>
            )}
            <ul className="mt-3 divide-y divide-gray-100">
              {trends.data.ingredients.map((ingredient) => (
                <li
                  key={ingredient.item_name}
                  className="flex items-center justify-between gap-3 py-2"
                >
                  <span className="text-sm text-gray-800">{ingredient.item_name}</span>
                  <div className="flex items-center gap-3">
                    <div className="h-10 w-32">
                      <ResponsiveContainer width="100%" height="100%">
                        <LineChart
                          data={ingredient.points.map((point) => ({
                            run: point.run_id,
                            pct:
                              point.variance_pct === null
                                ? null
                                : Number(point.variance_pct) * 100
                          }))}
                        >
                          <XAxis dataKey="run" hide />
                          <YAxis hide domain={['auto', 'auto']} />
                          <Tooltip formatter={(value) => `${Number(value).toFixed(1)}%`} />
                          <Line
                            type="monotone"
                            dataKey="pct"
                            stroke="#1d4ed8"
                            strokeWidth={2}
                            dot={{ r: 2 }}
                            isAnimationActive={false}
                          />
                        </LineChart>
                      </ResponsiveContainer>
                    </div>
                    <span className="w-16 text-right text-sm tabular-nums text-gray-700">
                      {ingredient.points.length > 0 &&
                      ingredient.points[ingredient.points.length - 1].variance_pct !== null
                        ? `${(Number(ingredient.points[ingredient.points.length - 1].variance_pct) * 100).toFixed(1)}%`
                        : '—'}
                    </span>
                  </div>
                </li>
              ))}
            </ul>
            {trends.data.drift_alerts.length === 0 && (
              <p className="mt-2 text-sm text-green-700">{t('production.leakage.noDrift')}</p>
            )}
          </>
        )}
      </div>
    </section>
  )
}
