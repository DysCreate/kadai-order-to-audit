import { useState, type FormEvent } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { apiErrorMessage } from '../../lib/apiError'
import { LoadingPanel, SkeletonText } from '../../components/Skeleton'
import { formatMoney } from '../../lib/money'
import { useAuth } from '../auth/AuthContext'
import {
  addRunOverhead,
  getCostSheet,
  type CostSheet,
  type OverheadCategory
} from './costingApi'

const WRITE_ROLES = ['production', 'admin', 'owner']

function SummaryCard({
  label,
  value,
  hint,
  tone
}: {
  label: string
  value: string
  hint?: string
  tone?: string
}) {
  return (
    <div className="rounded-lg border border-gray-200 bg-white p-4">
      <div className="text-sm text-gray-500">{label}</div>
      <div className={`mt-1 text-2xl font-semibold ${tone ?? 'text-gray-900'}`}>{value}</div>
      {hint && <div className="mt-1 text-xs text-gray-500">{hint}</div>}
    </div>
  )
}

export default function CostSheetPanel({ runId }: { runId: number }) {
  const { t } = useTranslation()
  const { user } = useAuth()
  const queryClient = useQueryClient()
  const canWrite = WRITE_ROLES.includes(user?.role ?? '')

  const [category, setCategory] = useState<OverheadCategory>('labour')
  const [amount, setAmount] = useState('')
  const [description, setDescription] = useState('')
  const [error, setError] = useState<string | null>(null)

  const sheet = useQuery({
    queryKey: ['cost-sheet', runId],
    queryFn: () => getCostSheet(runId)
  })

  const mutation = useMutation({
    mutationFn: () => addRunOverhead(runId, { category, amount, description }),
    onSuccess: (updated: CostSheet) => {
      setError(null)
      setAmount('')
      setDescription('')
      queryClient.setQueryData(['cost-sheet', runId], updated)
      queryClient.invalidateQueries({ queryKey: ['product-cost', updated.product_id] })
    },
    onError: (failure: unknown) => setError(apiErrorMessage(failure, t('costing.addError')))
  })

  if (sheet.isLoading)
    return (
      <LoadingPanel label={t('costing.loading')} className="p-2">
        <SkeletonText lines={5} />
      </LoadingPanel>
    )
  if (sheet.isError || !sheet.data)
    return (
      <p role="alert" className="p-2 text-red-700">
        {t('costing.loadError')}
      </p>
    )

  const data = sheet.data
  const marginTone =
    data.margin_per_packet?.startsWith('-') === true ? 'text-red-700' : 'text-green-700'

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError(null)
    mutation.mutate()
  }

  return (
    <section className="mt-8 space-y-4">
      <div>
        <h3 className="text-lg font-semibold text-gray-800">{t('costing.title')}</h3>
        <p className="text-sm text-gray-500">
          {t('costing.batchHours', {
            hours: data.batch_hours,
            standard: data.standard_batch_hours
          })}
        </p>
      </div>

      {error && (
        <div role="alert" className="rounded-md border border-red-300 bg-red-50 p-3 text-sm text-red-700">
          {error}
        </div>
      )}

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <SummaryCard label={t('costing.materials')} value={formatMoney(data.materials_value)} />
        <SummaryCard label={t('costing.overheads')} value={formatMoney(data.overhead_value)} />
        <SummaryCard label={t('costing.total')} value={formatMoney(data.total_cost)} />
        <SummaryCard
          label={t('costing.costPerPacket')}
          value={formatMoney(data.cost_per_packet)}
          hint={t('costing.goodPackets', { qty: data.good_packets })}
        />
        <SummaryCard
          label={t('costing.sellingPrice')}
          value={formatMoney(data.selling_price)}
        />
        <SummaryCard
          label={t('costing.margin')}
          value={formatMoney(data.margin_per_packet)}
          hint={
            data.margin_pct === null ? undefined : t('costing.marginPct', { pct: data.margin_pct })
          }
          tone={marginTone}
        />
        <SummaryCard
          label={t('costing.fgStock')}
          value={`${data.fg_stock_qty} ${data.product_uom}`}
          hint={t('costing.fgStockValue', { value: formatMoney(data.fg_stock_value) })}
        />
        <SummaryCard
          label={t('costing.fgAvgCost')}
          value={formatMoney(data.fg_avg_cost)}
          hint={t('costing.fgAvgHint')}
        />
      </div>

      <div className="overflow-x-auto rounded-lg border border-gray-200 bg-white">
        <table className="min-w-full divide-y divide-gray-200">
          <thead className="bg-gray-50">
            <tr>
              <th className="px-4 py-3 text-left text-sm font-semibold text-gray-600">
                {t('costing.input')}
              </th>
              <th className="px-4 py-3 text-right text-sm font-semibold text-gray-600">
                {t('costing.qty')}
              </th>
              <th className="px-4 py-3 text-right text-sm font-semibold text-gray-600">
                {t('costing.value')}
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {data.materials.map((line) => (
              <tr key={line.item_id}>
                <td className="px-4 py-3 text-gray-900">{line.item_name}</td>
                <td className="px-4 py-3 text-right tabular-nums text-gray-700">
                  {line.qty} {line.uom}
                </td>
                <td className="px-4 py-3 text-right tabular-nums text-gray-700">
                  {formatMoney(line.value)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="overflow-x-auto rounded-lg border border-gray-200 bg-white">
        <table className="min-w-full divide-y divide-gray-200">
          <thead className="bg-gray-50">
            <tr>
              <th className="px-4 py-3 text-left text-sm font-semibold text-gray-600">
                {t('costing.overhead')}
              </th>
              <th className="px-4 py-3 text-left text-sm font-semibold text-gray-600">
                {t('costing.description')}
              </th>
              <th className="px-4 py-3 text-right text-sm font-semibold text-gray-600">
                {t('costing.amount')}
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {data.overheads.length === 0 && (
              <tr>
                <td className="px-4 py-3 text-sm text-gray-500" colSpan={3}>
                  {t('costing.emptyOverheads')}
                </td>
              </tr>
            )}
            {data.overheads.map((line) => (
              <tr key={`${line.entry_id}-${line.allocation_id ?? 'run'}`}>
                <td className="px-4 py-3 text-gray-900">
                  {t(`costing.categories.${line.category}`)}
                  <span className="ml-2 rounded-full bg-gray-100 px-2 py-0.5 text-xs text-gray-600">
                    {t(`costing.scopes.${line.scope}`)}
                  </span>
                  {line.period && (
                    <span className="ml-2 text-xs text-gray-500">{line.period}</span>
                  )}
                </td>
                <td className="px-4 py-3 text-gray-700">{line.description || '—'}</td>
                <td className="px-4 py-3 text-right tabular-nums text-gray-700">
                  {formatMoney(line.amount)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {canWrite && (
        <form className="space-y-3 rounded-lg border border-gray-200 bg-white p-4" onSubmit={handleSubmit}>
          <h4 className="text-base font-semibold text-gray-800">{t('costing.addOverhead')}</h4>
          <div className="grid gap-3 sm:grid-cols-3">
            <div>
              <label htmlFor="overhead-category" className="block text-sm font-medium text-gray-700">
                {t('costing.category')}
              </label>
              <select
                id="overhead-category"
                value={category}
                onChange={(event) => setCategory(event.target.value as OverheadCategory)}
                className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500"
              >
                <option value="labour">{t('costing.categories.labour')}</option>
                <option value="power">{t('costing.categories.power')}</option>
                <option value="other">{t('costing.categories.other')}</option>
              </select>
            </div>
            <div>
              <label htmlFor="overhead-amount" className="block text-sm font-medium text-gray-700">
                {t('costing.amount')}
              </label>
              <input
                id="overhead-amount"
                type="number"
                inputMode="decimal"
                step="0.01"
                min="0.01"
                required
                value={amount}
                onChange={(event) => setAmount(event.target.value)}
                className="mt-1 block w-full rounded-md border-gray-300 text-right shadow-sm focus:border-blue-500 focus:ring-blue-500"
              />
            </div>
            <div>
              <label
                htmlFor="overhead-description"
                className="block text-sm font-medium text-gray-700"
              >
                {t('costing.description')}
              </label>
              <input
                id="overhead-description"
                type="text"
                value={description}
                onChange={(event) => setDescription(event.target.value)}
                className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500"
              />
            </div>
          </div>
          <button
            type="submit"
            disabled={mutation.isPending || amount.trim() === ''}
            className="min-h-[44px] rounded-md bg-blue-800 px-5 py-3 text-base font-medium text-white hover:bg-blue-700 disabled:opacity-50"
          >
            {mutation.isPending ? '…' : t('costing.addOverhead')}
          </button>
        </form>
      )}
    </section>
  )
}
