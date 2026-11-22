import { useState, type FormEvent } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { apiErrorMessage } from '../../lib/apiError'
import { formatMoney } from '../../lib/money'
import { Skeleton, SkeletonText } from '../../components/Skeleton'
import {
  getAgeing,
  getCustomerLedger,
  getOutstanding,
  listCustomers,
  recordPayment
} from '../sales/salesApi'

const METHODS = ['cash', 'upi', 'bank', 'cheque'] as const

export default function PaymentsPage() {
  const { t } = useTranslation()
  const queryClient = useQueryClient()

  const [customerId, setCustomerId] = useState<number | null>(null)
  const [amount, setAmount] = useState('')
  const [method, setMethod] = useState<(typeof METHODS)[number]>('upi')
  const [reference, setReference] = useState('')
  const [allocations, setAllocations] = useState<Record<number, string>>({})
  const [error, setError] = useState<string | null>(null)
  const [recorded, setRecorded] = useState<string | null>(null)

  const customers = useQuery({ queryKey: ['customers'], queryFn: listCustomers })
  const outstanding = useQuery({
    queryKey: ['outstanding', customerId],
    queryFn: () => getOutstanding(customerId as number),
    enabled: customerId !== null
  })
  const ageing = useQuery({
    queryKey: ['ageing', customerId],
    queryFn: () => getAgeing(customerId as number),
    enabled: customerId !== null
  })
  const ledger = useQuery({
    queryKey: ['ledger', customerId],
    queryFn: () => getCustomerLedger(customerId as number),
    enabled: customerId !== null
  })

  const mutation = useMutation({
    mutationFn: () =>
      recordPayment({
        customer: customerId as number,
        amount,
        method,
        reference,
        allocations: Object.entries(allocations)
          .filter(([, value]) => Number(value) > 0)
          .map(([invoice, value]) => ({ invoice: Number(invoice), amount: value }))
      }),
    onSuccess: (payment) => {
      setError(null)
      setRecorded(payment.amount)
      setAmount('')
      setReference('')
      setAllocations({})
      queryClient.invalidateQueries({ queryKey: ['outstanding', customerId] })
      queryClient.invalidateQueries({ queryKey: ['ageing', customerId] })
      queryClient.invalidateQueries({ queryKey: ['ledger', customerId] })
      queryClient.invalidateQueries({ queryKey: ['payments'] })
    },
    onError: (failure) => setError(apiErrorMessage(failure, t('payments.error')))
  })

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError(null)
    setRecorded(null)
    if (customerId === null) {
      setError(t('payments.chooseCustomer'))
      return
    }
    mutation.mutate()
  }

  const openInvoices = (ledger.data?.invoices ?? []).filter(
    (invoice) => Number(invoice.outstanding) > 0
  )

  return (
    <div className="mx-auto max-w-4xl p-4 sm:p-6">
      <h2 className="text-2xl font-semibold text-gray-800">{t('payments.title')}</h2>
      <p className="mt-1 text-sm text-gray-500">{t('payments.subtitle')}</p>

      <div className="mt-4">
        <label htmlFor="payment-customer" className="block text-sm font-medium text-gray-700">
          {t('payments.customer')}
        </label>
        <select
          id="payment-customer"
          value={customerId ?? ''}
          onChange={(event) => {
            const value = event.target.value
            setCustomerId(value === '' ? null : Number(value))
            setAllocations({})
            setError(null)
            setRecorded(null)
          }}
          className="mt-1 block min-h-[44px] w-full max-w-md rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500"
        >
          <option value="">{t('payments.chooseCustomer')}</option>
          {(customers.data ?? []).map((customer) => (
            <option key={customer.id} value={customer.id}>
              {customer.name}
            </option>
          ))}
        </select>
      </div>

      {error && (
        <div role="alert" className="mt-4 rounded-md border border-red-300 bg-red-50 p-3 text-sm text-red-700">
          {error}
        </div>
      )}
      {recorded && (
        <div role="status" className="mt-4 rounded-md border border-green-300 bg-green-50 p-3 text-sm text-green-800">
          {t('payments.recorded', { amount: formatMoney(recorded) })}
        </div>
      )}

      {customerId !== null && (
        <>
          <section className="mt-6 grid gap-3 sm:grid-cols-2">
            <div className="rounded-lg border border-gray-200 bg-white p-4">
              <div className="text-sm text-gray-500">{t('payments.outstanding')}</div>
              {outstanding.isLoading ? (
                <Skeleton className="mt-2 h-9 w-36" />
              ) : (
                <div className="text-3xl font-semibold text-gray-900">
                  {outstanding.data ? formatMoney(outstanding.data.outstanding) : '—'}
                </div>
              )}
            </div>
            <div className="rounded-lg border border-gray-200 bg-white p-4">
              <div className="text-sm text-gray-500">{t('payments.ageing')}</div>
              {ageing.isLoading && <SkeletonText lines={3} className="mt-1" />}
              <ul className="mt-1 space-y-1 text-sm">
                {(ageing.data?.buckets ?? []).map((bucket) => (
                  <li key={bucket.label} className="flex justify-between">
                    <span className="text-gray-600">{bucket.label}</span>
                    <span className="tabular-nums text-gray-900">{formatMoney(bucket.amount)}</span>
                  </li>
                ))}
              </ul>
            </div>
          </section>

          <form className="mt-6 space-y-3 rounded-lg border border-gray-200 bg-white p-4" onSubmit={handleSubmit}>
            <h3 className="text-lg font-semibold text-gray-800">{t('payments.record')}</h3>
            <div className="grid gap-3 sm:grid-cols-3">
              <div>
                <label htmlFor="payment-amount" className="block text-sm font-medium text-gray-700">
                  {t('payments.amount')}
                </label>
                <input
                  id="payment-amount"
                  type="number"
                  min="0.01"
                  step="0.01"
                  required
                  value={amount}
                  onChange={(event) => setAmount(event.target.value)}
                  className="mt-1 block min-h-[44px] w-full rounded-md border-gray-300 text-right tabular-nums shadow-sm focus:border-blue-500 focus:ring-blue-500"
                />
              </div>
              <div>
                <label htmlFor="payment-method" className="block text-sm font-medium text-gray-700">
                  {t('payments.method')}
                </label>
                <select
                  id="payment-method"
                  value={method}
                  onChange={(event) => setMethod(event.target.value as (typeof METHODS)[number])}
                  className="mt-1 block min-h-[44px] w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500"
                >
                  {METHODS.map((value) => (
                    <option key={value} value={value}>
                      {t(`payments.methods.${value}`)}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label htmlFor="payment-reference" className="block text-sm font-medium text-gray-700">
                  {t('payments.reference')}
                </label>
                <input
                  id="payment-reference"
                  type="text"
                  value={reference}
                  onChange={(event) => setReference(event.target.value)}
                  className="mt-1 block min-h-[44px] w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500"
                />
              </div>
            </div>

            <div>
              <div className="text-sm font-medium text-gray-700">{t('payments.allocate')}</div>
              <ul className="mt-1 divide-y divide-gray-100">
                {openInvoices.map((invoice) => (
                  <li key={invoice.invoice_id} className="flex items-center justify-between gap-3 py-2">
                    <div>
                      <div className="font-medium text-gray-900">{invoice.number}</div>
                      <div className="text-xs text-gray-500">
                        {t('payments.due', { amount: formatMoney(invoice.outstanding) })}
                      </div>
                    </div>
                    <input
                      type="number"
                      min="0"
                      step="0.01"
                      value={allocations[invoice.invoice_id] ?? ''}
                      aria-label={t('payments.allocateTo', { number: invoice.number })}
                      onChange={(event) =>
                        setAllocations((prev) => ({
                          ...prev,
                          [invoice.invoice_id]: event.target.value
                        }))
                      }
                      className="h-11 w-32 rounded-md border-gray-300 text-right tabular-nums shadow-sm focus:border-blue-500 focus:ring-blue-500"
                    />
                  </li>
                ))}
                {!ledger.isLoading && openInvoices.length === 0 && (
                  <li className="py-2 text-sm text-gray-500">{t('payments.noOpenInvoices')}</li>
                )}
              </ul>
            </div>

            <button
              type="submit"
              disabled={mutation.isPending || amount === ''}
              className="min-h-[44px] rounded-md bg-blue-800 px-4 py-2 font-semibold text-white hover:bg-blue-700 disabled:opacity-50"
            >
              {mutation.isPending ? '…' : t('payments.submit')}
            </button>
          </form>

          <section className="mt-6">
            <h3 className="text-lg font-semibold text-gray-800">{t('payments.ledger')}</h3>
            <div className="mt-2 overflow-x-auto rounded-lg border border-gray-200 bg-white">
              <table className="min-w-full divide-y divide-gray-200 text-sm">
                <thead className="bg-gray-50">
                  <tr>
                    <th className="px-3 py-2 text-left font-semibold text-gray-600">
                      {t('payments.invoice')}
                    </th>
                    <th className="px-3 py-2 text-left font-semibold text-gray-600">
                      {t('payments.date')}
                    </th>
                    <th className="px-3 py-2 text-right font-semibold text-gray-600">
                      {t('payments.total')}
                    </th>
                    <th className="px-3 py-2 text-right font-semibold text-gray-600">
                      {t('payments.paid')}
                    </th>
                    <th className="px-3 py-2 text-right font-semibold text-gray-600">
                      {t('payments.outstanding')}
                    </th>
                    <th className="px-3 py-2 text-right font-semibold text-gray-600">
                      {t('payments.age')}
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {ledger.isLoading &&
                    Array.from({ length: 3 }, (_, row) => (
                      <tr key={row}>
                        {Array.from({ length: 6 }, (_, column) => (
                          <td key={column} className="px-3 py-2">
                            <Skeleton className="h-4 w-full" />
                          </td>
                        ))}
                      </tr>
                    ))}
                  {!ledger.isLoading &&
                    (ledger.data?.invoices ?? []).map((invoice) => (
                      <tr key={invoice.invoice_id}>
                        <td className="px-3 py-2 font-medium text-gray-900">{invoice.number}</td>
                        <td className="px-3 py-2 text-gray-700">{invoice.invoice_date}</td>
                        <td className="px-3 py-2 text-right tabular-nums text-gray-700">
                          {formatMoney(invoice.total)}
                        </td>
                        <td className="px-3 py-2 text-right tabular-nums text-gray-700">
                          {formatMoney(invoice.paid)}
                        </td>
                        <td className="px-3 py-2 text-right tabular-nums text-gray-900">
                          {formatMoney(invoice.outstanding)}
                        </td>
                        <td className="px-3 py-2 text-right tabular-nums text-gray-700">
                          {invoice.age_days}
                        </td>
                      </tr>
                    ))}
                </tbody>
              </table>
            </div>

            <h4 className="mt-4 text-sm font-semibold text-gray-700">{t('payments.payments')}</h4>
            <ul className="mt-1 space-y-2 text-sm">
              {(ledger.data?.payments ?? []).map((payment) => (
                <li key={payment.id} className="rounded border border-gray-200 bg-white p-3">
                  <div className="flex justify-between">
                    <span className="font-medium text-gray-900">
                      {formatMoney(payment.amount)} · {t(`payments.methods.${payment.method}`)}
                    </span>
                    <span className="text-gray-600">{payment.payment_date}</span>
                  </div>
                  {payment.allocations.length > 0 && (
                    <div className="mt-1 text-xs text-gray-500">
                      {payment.allocations
                        .map(
                          (allocation) =>
                            `${allocation.invoice_number}: ${formatMoney(allocation.amount)}`
                        )
                        .join(' · ')}
                    </div>
                  )}
                </li>
              ))}
              {!ledger.isLoading && (ledger.data?.payments ?? []).length === 0 && (
                <li className="text-gray-500">{t('sales.invoice.none')}</li>
              )}
            </ul>
          </section>
        </>
      )}
    </div>
  )
}
