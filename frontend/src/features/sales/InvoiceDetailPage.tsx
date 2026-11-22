import { useEffect, useState, type FormEvent } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { useParams } from 'react-router-dom'
import { apiErrorMessage } from '../../lib/apiError'
import { SkeletonDetailPage } from '../../components/Skeleton'
import { formatMoney } from '../../lib/money'
import { useAuth } from '../auth/AuthContext'
import {
  createCreditNote,
  dispatchInvoice,
  getInvoice,
  getShareLinks,
  invoicePdfPath
} from './salesApi'

export default function InvoiceDetailPage() {
  const { t } = useTranslation()
  const params = useParams()
  const invoiceId = Number(params.id)
  const queryClient = useQueryClient()
  const { user } = useAuth()

  const [dispatchQty, setDispatchQty] = useState<Record<number, string>>({})
  const [creditQty, setCreditQty] = useState<Record<number, string>>({})
  const [reason, setReason] = useState('')
  const [restock, setRestock] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const invoice = useQuery({
    queryKey: ['invoice', invoiceId],
    queryFn: () => getInvoice(invoiceId)
  })

  const canShare = user?.role === 'admin' || user?.role === 'owner'
  const share = useQuery({
    queryKey: ['invoice-share', invoiceId],
    queryFn: () => getShareLinks(invoiceId),
    enabled: canShare && invoice.isSuccess
  })

  useEffect(() => {
    if (!invoice.data) return
    const nextDispatch: Record<number, string> = {}
    const nextCredit: Record<number, string> = {}
    for (const line of invoice.data.lines) {
      nextDispatch[line.id] = line.remaining_qty
      nextCredit[line.id] = '0'
    }
    setDispatchQty(nextDispatch)
    setCreditQty(nextCredit)
    setReason('')
  }, [invoice.data?.id, invoice.data?.dispatched_total, invoice.data?.credited_total]) // eslint-disable-line react-hooks/exhaustive-deps

  const refresh = () => {
    setError(null)
    queryClient.invalidateQueries({ queryKey: ['invoice', invoiceId] })
    queryClient.invalidateQueries({ queryKey: ['invoices'] })
    queryClient.invalidateQueries({ queryKey: ['invoice-share', invoiceId] })
  }
  const onFailure = (fallback: string) => (failure: unknown) =>
    setError(apiErrorMessage(failure, fallback))

  const dispatchMutation = useMutation({
    mutationFn: () =>
      dispatchInvoice(invoiceId, {
        lines: (invoice.data?.lines ?? [])
          .filter((line) => Number(dispatchQty[line.id] ?? '0') > 0)
          .map((line) => ({ invoice_line: line.id, qty: dispatchQty[line.id] ?? '0' }))
      }),
    onSuccess: refresh,
    onError: onFailure(t('sales.invoice.dispatchError'))
  })

  const creditMutation = useMutation({
    mutationFn: () =>
      createCreditNote(invoiceId, {
        reason,
        restock,
        lines: (invoice.data?.lines ?? [])
          .filter((line) => Number(creditQty[line.id] ?? '0') > 0)
          .map((line) => ({ invoice_line: line.id, qty: creditQty[line.id] ?? '0' }))
      }),
    onSuccess: refresh,
    onError: onFailure(t('sales.invoice.creditError'))
  })

  if (invoice.isLoading) return <SkeletonDetailPage label={t('sales.loading')} />
  if (invoice.isError || !invoice.data)
    return (
      <p role="alert" className="p-6 text-red-700">
        {t('sales.invoice.loadError')}
      </p>
    )

  const data = invoice.data
  const hasRemaining = data.lines.some((line) => Number(line.remaining_qty) > 0)
  const canCredit = !data.is_cancelled

  function handleDispatch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError(null)
    dispatchMutation.mutate()
  }

  function handleCredit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError(null)
    creditMutation.mutate()
  }

  return (
    <div className="mx-auto max-w-4xl p-4 sm:p-6">
      <header className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h2 className="text-2xl font-semibold text-gray-800">{data.number}</h2>
          <p className="mt-1 text-sm text-gray-500">
            {data.customer_name} · {data.invoice_date} ·{' '}
            {t('sales.invoice.placeOfSupply', { code: data.place_of_supply_state_code })}
          </p>
          <p className="text-sm text-gray-500">
            {data.is_interstate ? t('sales.invoice.interState') : t('sales.invoice.intraState')}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <a
            href={invoicePdfPath(data.id)}
            target="_blank"
            rel="noreferrer"
            className="inline-flex min-h-[44px] items-center rounded-md border border-blue-300 bg-white px-4 py-2 text-sm font-medium text-blue-800 hover:bg-blue-50"
          >
            {t('sales.invoice.openPdf')}
          </a>
          {share.data && (
            <>
              <a
                href={share.data.whatsapp}
                target="_blank"
                rel="noreferrer"
                className="inline-flex min-h-[44px] items-center rounded-md bg-green-700 px-4 py-2 text-sm font-medium text-white hover:bg-green-600"
              >
                {t('sales.invoice.whatsapp')}
              </a>
              <a
                href={share.data.mailto}
                className="inline-flex min-h-[44px] items-center rounded-md border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"
              >
                {t('sales.invoice.email')}
              </a>
            </>
          )}
          <span
            className={`inline-flex items-center rounded-full px-3 py-1 text-sm font-medium ${
              data.is_cancelled ? 'bg-red-100 text-red-800' : 'bg-green-100 text-green-800'
            }`}
          >
            {data.is_cancelled ? t('sales.invoices.cancelled') : t('sales.invoices.posted')}
          </span>
        </div>
      </header>

      {error && (
        <div role="alert" className="mt-4 rounded-md border border-red-300 bg-red-50 p-3 text-sm text-red-700">
          {error}
        </div>
      )}

      <section className="mt-6 overflow-x-auto rounded-lg border border-gray-200 bg-white">
        <table className="min-w-full divide-y divide-gray-200 text-sm">
          <thead className="bg-gray-50">
            <tr>
              <th className="px-3 py-2 text-left font-semibold text-gray-600">
                {t('sales.invoice.description')}
              </th>
              <th className="px-3 py-2 text-right font-semibold text-gray-600">
                {t('sales.invoice.hsn')}
              </th>
              <th className="px-3 py-2 text-right font-semibold text-gray-600">
                {t('sales.invoice.qty')}
              </th>
              <th className="px-3 py-2 text-right font-semibold text-gray-600">
                {t('sales.invoice.rate')}
              </th>
              <th className="px-3 py-2 text-right font-semibold text-gray-600">
                {t('sales.invoice.taxable')}
              </th>
              <th className="px-3 py-2 text-right font-semibold text-gray-600">
                {data.is_interstate ? 'IGST' : 'CGST + SGST'}
              </th>
              <th className="px-3 py-2 text-right font-semibold text-gray-600">
                {t('sales.invoice.total')}
              </th>
              <th className="px-3 py-2 text-right font-semibold text-gray-600">
                {t('sales.invoice.remaining')}
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {data.lines.map((line) => (
              <tr key={line.id}>
                <td className="px-3 py-2">
                  <div className="font-medium text-gray-900">{line.description}</div>
                  <div className="text-xs text-gray-500">
                    {t('sales.invoice.dispatchedCredited', {
                      dispatched: line.dispatched_qty,
                      credited: line.credited_qty
                    })}
                  </div>
                </td>
                <td className="px-3 py-2 text-right tabular-nums text-gray-700">{line.hsn_code}</td>
                <td className="px-3 py-2 text-right tabular-nums text-gray-700">
                  {line.qty} {line.uom}
                </td>
                <td className="px-3 py-2 text-right tabular-nums text-gray-700">
                  {formatMoney(line.unit_price)}
                </td>
                <td className="px-3 py-2 text-right tabular-nums text-gray-700">
                  {formatMoney(line.taxable_value)}
                </td>
                <td className="px-3 py-2 text-right tabular-nums text-gray-700">
                  {formatMoney(data.is_interstate ? line.igst : line.cgst)}
                  {!data.is_interstate && ` + ${formatMoney(line.sgst)}`}
                </td>
                <td className="px-3 py-2 text-right tabular-nums text-gray-900">
                  {formatMoney(line.line_total)}
                </td>
                <td className="px-3 py-2 text-right tabular-nums text-gray-700">
                  {line.remaining_qty}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section className="mt-4 grid gap-3 sm:grid-cols-2">
        <div className="rounded-lg border border-gray-200 bg-white p-4 text-sm">
          <div className="flex justify-between py-1">
            <span className="text-gray-600">{t('sales.invoice.taxable')}</span>
            <span className="tabular-nums text-gray-900">{formatMoney(data.taxable_total)}</span>
          </div>
          {data.is_interstate ? (
            <div className="flex justify-between py-1">
              <span className="text-gray-600">IGST</span>
              <span className="tabular-nums text-gray-900">{formatMoney(data.igst_total)}</span>
            </div>
          ) : (
            <>
              <div className="flex justify-between py-1">
                <span className="text-gray-600">CGST</span>
                <span className="tabular-nums text-gray-900">{formatMoney(data.cgst_total)}</span>
              </div>
              <div className="flex justify-between py-1">
                <span className="text-gray-600">SGST</span>
                <span className="tabular-nums text-gray-900">{formatMoney(data.sgst_total)}</span>
              </div>
            </>
          )}
          <div className="flex justify-between py-1">
            <span className="text-gray-600">{t('sales.invoice.roundOff')}</span>
            <span className="tabular-nums text-gray-900">{formatMoney(data.round_off)}</span>
          </div>
          <div className="mt-2 flex justify-between border-t border-gray-300 pt-2 text-base font-semibold">
            <span>{t('sales.invoice.total')}</span>
            <span className="tabular-nums">{formatMoney(data.total)}</span>
          </div>
          <p className="mt-2 text-xs italic text-gray-500">{data.amount_in_words}</p>
        </div>

        <div className="rounded-lg border border-gray-200 bg-white p-4 text-sm">
          <div className="text-gray-600">{t('sales.invoice.creditedTotal')}</div>
          <div className="text-lg font-semibold text-gray-900">
            {formatMoney(data.credited_total)}
          </div>
          <div className="mt-3 text-gray-600">{t('sales.invoice.dispatchedTotal')}</div>
          <div className="text-lg font-semibold text-gray-900">
            {formatMoney(data.dispatched_total)}
          </div>
          <div className="mt-3 text-gray-600">{t('sales.invoice.creditNotes')}</div>
          <ul className="mt-1 space-y-1">
            {data.credit_notes.map((note) => (
              <li key={note.id} className="flex justify-between">
                <span>{note.number}</span>
                <span className="tabular-nums">{formatMoney(note.total)}</span>
              </li>
            ))}
            {data.credit_notes.length === 0 && (
              <li className="text-gray-500">{t('sales.invoice.none')}</li>
            )}
          </ul>
        </div>
      </section>

      {hasRemaining && !data.is_cancelled && (
        <form className="mt-6 space-y-3 rounded-lg border border-gray-200 bg-white p-4" onSubmit={handleDispatch}>
          <h3 className="text-lg font-semibold text-gray-800">{t('sales.invoice.dispatchTitle')}</h3>
          <p className="text-sm text-gray-500">{t('sales.invoice.dispatchHint')}</p>
          <div className="divide-y divide-gray-100">
            {data.lines.map((line) => (
              <div key={line.id} className="flex items-center justify-between gap-3 py-2">
                <div>
                  <div className="font-medium text-gray-900">{line.description}</div>
                  <div className="text-xs text-gray-500">
                    {t('sales.invoice.remainingQty', { qty: line.remaining_qty, uom: line.uom })}
                  </div>
                </div>
                <input
                  type="number"
                  min="0"
                  max={line.remaining_qty}
                  step="0.001"
                  value={dispatchQty[line.id] ?? '0'}
                  aria-label={t('sales.invoice.dispatchQtyFor', { item: line.description })}
                  onChange={(event) =>
                    setDispatchQty((prev) => ({ ...prev, [line.id]: event.target.value }))
                  }
                  className="h-11 w-24 rounded-md border-gray-300 text-right tabular-nums shadow-sm focus:border-blue-500 focus:ring-blue-500"
                />
              </div>
            ))}
          </div>
          <button
            type="submit"
            disabled={dispatchMutation.isPending}
            className="min-h-[44px] rounded-md bg-blue-800 px-4 py-2 font-semibold text-white hover:bg-blue-700 disabled:opacity-50"
          >
            {t('sales.invoice.dispatch')}
          </button>
        </form>
      )}

      {canCredit && (
        <form className="mt-6 space-y-3 rounded-lg border border-gray-200 bg-white p-4" onSubmit={handleCredit}>
          <h3 className="text-lg font-semibold text-gray-800">{t('sales.invoice.creditTitle')}</h3>
          <p className="text-sm text-gray-500">{t('sales.invoice.creditHint')}</p>
          <div className="divide-y divide-gray-100">
            {data.lines.map((line) => (
              <div key={line.id} className="flex items-center justify-between gap-3 py-2">
                <div>
                  <div className="font-medium text-gray-900">{line.description}</div>
                  <div className="text-xs text-gray-500">
                    {t('sales.invoice.invoicedQty', { qty: line.qty, uom: line.uom })}
                  </div>
                </div>
                <input
                  type="number"
                  min="0"
                  step="0.001"
                  value={creditQty[line.id] ?? '0'}
                  aria-label={t('sales.invoice.creditQtyFor', { item: line.description })}
                  onChange={(event) =>
                    setCreditQty((prev) => ({ ...prev, [line.id]: event.target.value }))
                  }
                  className="h-11 w-24 rounded-md border-gray-300 text-right tabular-nums shadow-sm focus:border-blue-500 focus:ring-blue-500"
                />
              </div>
            ))}
          </div>
          <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
            <input
              type="text"
              value={reason}
              onChange={(event) => setReason(event.target.value)}
              placeholder={t('sales.invoice.creditReason')}
              aria-label={t('sales.invoice.creditReason')}
              className="min-h-[44px] flex-1 rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500"
            />
            <label className="flex min-h-[44px] items-center gap-2 text-sm text-gray-700">
              <input
                type="checkbox"
                checked={restock}
                onChange={(event) => setRestock(event.target.checked)}
                className="h-5 w-5 rounded border-gray-300"
              />
              {t('sales.invoice.restock')}
            </label>
            <button
              type="submit"
              disabled={creditMutation.isPending || reason.trim() === ''}
              className="min-h-[44px] rounded-md border border-red-300 bg-white px-4 py-2 font-medium text-red-700 hover:bg-red-50 disabled:opacity-50"
            >
              {t('sales.invoice.creditSubmit')}
            </button>
          </div>
        </form>
      )}

      <section className="mt-6">
        <h3 className="text-lg font-semibold text-gray-800">{t('sales.invoice.dispatches')}</h3>
        <ul className="mt-2 space-y-2 text-sm">
          {data.dispatches.map((dispatch) => (
            <li key={dispatch.id} className="rounded border border-gray-200 bg-white p-3">
              <div className="font-medium text-gray-900">
                {t('sales.invoice.dispatchLabel', {
                  id: dispatch.id,
                  date: dispatch.dispatch_date
                })}
              </div>
              <div className="text-gray-600">
                {dispatch.lines
                  .map((line) => `${line.item_name} × ${line.qty}`)
                  .join(', ')}
              </div>
            </li>
          ))}
          {data.dispatches.length === 0 && (
            <li className="text-gray-500">{t('sales.invoice.none')}</li>
          )}
        </ul>
      </section>
    </div>
  )
}
