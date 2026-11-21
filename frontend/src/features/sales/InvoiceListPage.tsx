import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import { formatMoney } from '../../lib/money'
import { listInvoices } from './salesApi'

export default function InvoiceListPage() {
  const { t } = useTranslation()
  const { data, isLoading, isError } = useQuery({
    queryKey: ['invoices'],
    queryFn: listInvoices
  })

  return (
    <div className="p-4 sm:p-6">
      <h2 className="text-2xl font-semibold text-gray-800">{t('sales.invoices.title')}</h2>
      <p className="mt-1 text-sm text-gray-500">{t('sales.invoices.subtitle')}</p>

      {isLoading && <p className="mt-6 text-gray-500">{t('sales.loading')}</p>}
      {isError && (
        <p role="alert" className="mt-6 text-red-700">
          {t('sales.invoices.loadError')}
        </p>
      )}
      {data && data.length === 0 && <p className="mt-6 text-gray-500">{t('sales.invoices.empty')}</p>}

      {data && data.length > 0 && (
        <ul className="mt-6 space-y-3">
          {data.map((invoice) => (
            <li key={invoice.id}>
              <Link
                to={`/invoices/${invoice.id}`}
                className="flex min-h-[64px] flex-col gap-2 rounded-lg border border-gray-200 bg-white p-4 shadow-sm hover:border-blue-400 sm:flex-row sm:items-center sm:justify-between"
              >
                <div>
                  <div className="text-lg font-semibold text-gray-900">{invoice.number}</div>
                  <div className="text-sm text-gray-500">
                    {invoice.customer_name} · {invoice.invoice_date}
                  </div>
                </div>
                <div className="flex items-center gap-3">
                  <span className="text-lg font-semibold text-gray-900">
                    {formatMoney(invoice.total)}
                  </span>
                  <span
                    className={`inline-flex rounded-full px-3 py-1 text-sm font-medium ${
                      invoice.is_cancelled
                        ? 'bg-red-100 text-red-800'
                        : 'bg-green-100 text-green-800'
                    }`}
                  >
                    {invoice.is_cancelled
                      ? t('sales.invoices.cancelled')
                      : t('sales.invoices.posted')}
                  </span>
                </div>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
