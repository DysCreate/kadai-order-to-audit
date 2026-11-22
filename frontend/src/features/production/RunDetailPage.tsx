import { useEffect, useState, type FormEvent } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { useParams } from 'react-router-dom'
import {
  amendRun,
  completeRun,
  getRun,
  issueRun,
  type IssueLineInput,
  type ProductionRun,
  type RunLine,
  type VarianceRow
} from './productionApi'
import CostSheetPanel from '../costing/CostSheetPanel'
import { formatPct, previewVariance, type VariancePreview } from './variance'
import { SkeletonDetailPage } from '../../components/Skeleton'

function apiErrorMessage(error: unknown, fallback: string): string {
  const detail = (error as { response?: { data?: { detail?: string; code?: string } } })?.response
    ?.data
  return detail?.detail ?? detail?.code ?? fallback
}

function Chip({ preview }: { preview: VariancePreview }) {
  const { t } = useTranslation()
  const tone = preview.flagged
    ? preview.direction === 'adverse'
      ? 'bg-red-100 text-red-800 border-red-200'
      : 'bg-green-100 text-green-800 border-green-200'
    : 'bg-gray-100 text-gray-600 border-gray-200'
  return (
    <span className={`inline-flex items-center rounded-full border px-3 py-1 text-sm font-medium ${tone}`}>
      {formatPct(preview.pct)}
      {preview.flagged && (
        <span className="ml-2 text-xs uppercase tracking-wide">
          {t(`production.variance.${preview.direction}`)}
        </span>
      )}
    </span>
  )
}

function StoredChip({ row }: { row: VarianceRow }) {
  const { t } = useTranslation()
  const tone = row.flagged
    ? row.direction === 'adverse'
      ? 'bg-red-100 text-red-800 border-red-200'
      : 'bg-green-100 text-green-800 border-green-200'
    : 'bg-gray-100 text-gray-600 border-gray-200'
  const pct = row.variance_pct === null ? null : Number(row.variance_pct)
  return (
    <span className={`inline-flex items-center rounded-full border px-3 py-1 text-sm font-medium ${tone}`}>
      {formatPct(pct)}
      {row.flagged && (
        <span className="ml-2 text-xs uppercase tracking-wide">
          {t(`production.variance.${row.direction}`)}
        </span>
      )}
    </span>
  )
}

function QuantityInput({
  id,
  label,
  value,
  onChange,
  disabled
}: {
  id: string
  label: string
  value: string
  onChange: (value: string) => void
  disabled?: boolean
}) {
  return (
    <div>
      <label htmlFor={id} className="block text-sm font-medium text-gray-700">
        {label}
      </label>
      <input
        id={id}
        type="number"
        inputMode="decimal"
        step="0.001"
        min="0"
        disabled={disabled}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="mt-1 block w-40 rounded-md border-gray-300 text-right text-2xl font-semibold shadow-sm focus:border-blue-500 focus:ring-blue-500 disabled:bg-gray-100"
      />
    </div>
  )
}

export default function RunDetailPage() {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const params = useParams()
  const runId = Number(params.id)

  const { data: run, isLoading, isError } = useQuery({
    queryKey: ['production-run', runId],
    queryFn: () => getRun(runId)
  })

  const [issued, setIssued] = useState<Record<number, string>>({})
  const [goodPackets, setGoodPackets] = useState('')
  const [damagedPouches, setDamagedPouches] = useState('0')
  const [cartonsUsed, setCartonsUsed] = useState('0')
  const [reason, setReason] = useState('')
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!run) return
    const next: Record<number, string> = {}
    for (const line of run.lines) {
      next[line.id] = line.role === 'material' ? line.planned_qty : '0'
    }
    setIssued(next)
    setGoodPackets(run.planned_output_qty)
    setDamagedPouches('0')
    setCartonsUsed('0')
    setReason('')
  }, [run?.id, run?.state]) // eslint-disable-line react-hooks/exhaustive-deps

  const refresh = (updated: ProductionRun) => {
    queryClient.setQueryData(['production-run', runId], updated)
    queryClient.invalidateQueries({ queryKey: ['production-runs'] })
  }
  const onFailure = (fallback: string) => (failure: unknown) =>
    setError(apiErrorMessage(failure, fallback))

  const issueMutation = useMutation({
    mutationFn: (lines: IssueLineInput[]) => issueRun(runId, lines),
    onSuccess: (updated) => {
      setError(null)
      refresh(updated)
    },
    onError: onFailure(t('production.issue.error'))
  })

  const completeMutation = useMutation({
    mutationFn: () =>
      completeRun(runId, {
        good_packets: goodPackets,
        damaged_pouches: damagedPouches,
        cartons_used: cartonsUsed
      }),
    onSuccess: (updated) => {
      setError(null)
      refresh(updated)
    },
    onError: onFailure(t('production.complete.error'))
  })

  const amendMutation = useMutation({
    mutationFn: () => amendRun(runId, reason),
    onSuccess: (updated) => {
      setError(null)
      refresh(updated)
    },
    onError: onFailure(t('production.amend.error'))
  })

  if (isLoading) return <SkeletonDetailPage label={t('production.loading')} />
  if (isError || !run)
    return (
      <p role="alert" className="p-6 text-red-700">
        {t('production.loadError')}
      </p>
    )

  const activeRun: ProductionRun = run
  const tolerance = Number(activeRun.tolerance)
  const pouchLine = run.lines.find((line) => line.role === 'pouch')
  const cartonLine = run.lines.find((line) => line.role === 'carton')
  const yieldPreview = previewVariance(
    run.planned_output_qty,
    Number(goodPackets),
    tolerance,
    true
  )
  const pouchPreview = pouchLine
    ? previewVariance(
        pouchLine.planned_qty,
        Number(goodPackets) + Number(damagedPouches),
        tolerance
      )
    : null
  const cartonPreview = cartonLine
    ? previewVariance(cartonLine.planned_qty, Number(cartonsUsed), tolerance)
    : null

  function handleIssue(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError(null)
    issueMutation.mutate(
      activeRun.lines.map((line: RunLine) => ({ line: line.id, qty: issued[line.id] ?? '0' }))
    )
  }

  function handleComplete(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError(null)
    completeMutation.mutate()
  }

  function handleAmend(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError(null)
    amendMutation.mutate()
  }

  return (
    <div className="p-4 sm:p-6">
      <header className="flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h2 className="text-2xl font-semibold text-gray-800">
            {t('production.runLabel', { id: run.id })} · {run.product_name}
          </h2>
          <p className="mt-1 text-sm text-gray-500">
            {t('production.bomVersion', { version: run.bom_version })} ·{' '}
            {t('production.batches', { batches: run.batches })} ·{' '}
            {t('production.tolerance', { pct: `${(tolerance * 100).toFixed(1)}%` })}
          </p>
        </div>
        <span className="inline-flex w-fit items-center rounded-full bg-blue-100 px-3 py-1 text-sm font-medium text-blue-800">
          {t(`production.states.${run.state}`)}
        </span>
      </header>

      {error && (
        <div role="alert" className="mt-4 rounded-md border border-red-300 bg-red-50 p-3 text-sm text-red-700">
          {error}
        </div>
      )}

      {run.state === 'DRAFT' && (
        <form className="mt-6 space-y-4" onSubmit={handleIssue}>
          <h3 className="text-lg font-semibold text-gray-800">{t('production.issue.title')}</h3>
          <p className="text-sm text-gray-500">{t('production.issue.hint')}</p>
          <div className="divide-y divide-gray-200 rounded-lg border border-gray-200 bg-white">
            {run.lines.map((line) => (
              <div
                key={line.id}
                className="flex flex-col gap-3 p-4 sm:flex-row sm:items-end sm:justify-between"
              >
                <div>
                  <div className="text-lg font-medium text-gray-900">{line.item_name}</div>
                  <div className="text-sm text-gray-500">
                    {t('production.plan', { qty: line.planned_qty, uom: line.uom })}
                  </div>
                </div>
                <div className="flex items-end gap-3">
                  <QuantityInput
                    id={`issued-${line.id}`}
                    label={t('production.issue.issuedQty')}
                    value={issued[line.id] ?? '0'}
                    onChange={(value) => setIssued((prev) => ({ ...prev, [line.id]: value }))}
                  />
                  <Chip
                    preview={previewVariance(
                      line.planned_qty,
                      Number(issued[line.id] ?? '0'),
                      tolerance
                    )}
                  />
                </div>
              </div>
            ))}
          </div>
          <button
            type="submit"
            disabled={issueMutation.isPending}
            className="min-h-[44px] rounded-md bg-blue-800 px-5 py-3 text-base font-medium text-white hover:bg-blue-700 disabled:opacity-50"
          >
            {issueMutation.isPending ? '…' : t('production.issue.submit')}
          </button>
        </form>
      )}

      {run.state === 'ISSUED' && (
        <>
          <form className="mt-6 space-y-4" onSubmit={handleComplete}>
            <h3 className="text-lg font-semibold text-gray-800">
              {t('production.complete.title')}
            </h3>
            <p className="text-sm text-gray-500">{t('production.complete.hint')}</p>
            <div className="grid gap-4 rounded-lg border border-gray-200 bg-white p-4 sm:grid-cols-2 xl:grid-cols-3">
              <div className="space-y-2">
                <QuantityInput
                  id="good-packets"
                  label={t('production.complete.goodPackets')}
                  value={goodPackets}
                  onChange={setGoodPackets}
                />
                <Chip preview={yieldPreview} />
                <p className="text-xs text-gray-500">
                  {t('production.variance.yieldHint', { qty: run.planned_output_qty })}
                </p>
              </div>
              <div className="space-y-2">
                <QuantityInput
                  id="damaged-pouches"
                  label={t('production.complete.damagedPouches')}
                  value={damagedPouches}
                  onChange={setDamagedPouches}
                />
                {pouchPreview && <Chip preview={pouchPreview} />}
                {pouchLine && (
                  <p className="text-xs text-gray-500">
                    {t('production.variance.pouchHint', { qty: pouchLine.planned_qty })}
                  </p>
                )}
              </div>
              <div className="space-y-2">
                <QuantityInput
                  id="cartons-used"
                  label={t('production.complete.cartonsUsed')}
                  value={cartonsUsed}
                  onChange={setCartonsUsed}
                />
                {cartonPreview && <Chip preview={cartonPreview} />}
                {cartonLine && (
                  <p className="text-xs text-gray-500">
                    {t('production.variance.cartonHint', { qty: cartonLine.planned_qty })}
                  </p>
                )}
              </div>
            </div>
            <button
              type="submit"
              disabled={completeMutation.isPending}
              className="min-h-[44px] rounded-md bg-blue-800 px-5 py-3 text-base font-medium text-white hover:bg-blue-700 disabled:opacity-50"
            >
              {completeMutation.isPending ? '…' : t('production.complete.submit')}
            </button>
          </form>

          <form className="mt-8 space-y-3" onSubmit={handleAmend}>
            <h3 className="text-lg font-semibold text-gray-800">{t('production.amend.title')}</h3>
            <p className="text-sm text-gray-500">{t('production.amend.hint')}</p>
            <div className="flex flex-col gap-3 sm:flex-row sm:items-end">
              <div className="flex-1">
                <label htmlFor="amend-reason" className="block text-sm font-medium text-gray-700">
                  {t('production.amend.reason')}
                </label>
                <input
                  id="amend-reason"
                  type="text"
                  value={reason}
                  onChange={(event) => setReason(event.target.value)}
                  className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500"
                />
              </div>
              <button
                type="submit"
                disabled={amendMutation.isPending || reason.trim() === ''}
                className="min-h-[44px] rounded-md border border-red-300 bg-white px-5 py-3 text-base font-medium text-red-700 hover:bg-red-50 disabled:opacity-50"
              >
                {t('production.amend.submit')}
              </button>
            </div>
          </form>
        </>
      )}

      {run.state === 'COMPLETED' && (
        <section className="mt-6 space-y-4">
          <div className="grid gap-4 sm:grid-cols-3">
            <div className="rounded-lg border border-gray-200 bg-white p-4">
              <div className="text-sm text-gray-500">{t('production.complete.goodPackets')}</div>
              <div className="text-2xl font-semibold text-gray-900">{run.good_packets}</div>
            </div>
            <div className="rounded-lg border border-gray-200 bg-white p-4">
              <div className="text-sm text-gray-500">{t('production.complete.damagedPouches')}</div>
              <div className="text-2xl font-semibold text-gray-900">{run.damaged_pouches}</div>
            </div>
            <div className="rounded-lg border border-gray-200 bg-white p-4">
              <div className="text-sm text-gray-500">{t('production.complete.cartonsUsed')}</div>
              <div className="text-2xl font-semibold text-gray-900">{run.cartons_used}</div>
            </div>
          </div>

          <h3 className="text-lg font-semibold text-gray-800">{t('production.variance.title')}</h3>
          <div className="overflow-x-auto rounded-lg border border-gray-200 bg-white">
            <table className="min-w-full divide-y divide-gray-200">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-4 py-3 text-left text-sm font-semibold text-gray-600">
                    {t('production.variance.input')}
                  </th>
                  <th className="px-4 py-3 text-right text-sm font-semibold text-gray-600">
                    {t('production.variance.planned')}
                  </th>
                  <th className="px-4 py-3 text-right text-sm font-semibold text-gray-600">
                    {t('production.variance.actual')}
                  </th>
                  <th className="px-4 py-3 text-left text-sm font-semibold text-gray-600">
                    {t('production.variance.variance')}
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {run.variance.map((row) => (
                  <tr key={`${row.kind}-${row.line_id ?? 'yield'}`}>
                    <td className="px-4 py-3 text-gray-900">{row.item_name}</td>
                    <td className="px-4 py-3 text-right tabular-nums text-gray-700">
                      {row.planned_qty}
                    </td>
                    <td className="px-4 py-3 text-right tabular-nums text-gray-700">
                      {row.actual_qty}
                    </td>
                    <td className="px-4 py-3">
                      <StoredChip row={row} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <CostSheetPanel runId={run.id} />
        </section>
      )}
    </div>
  )
}
