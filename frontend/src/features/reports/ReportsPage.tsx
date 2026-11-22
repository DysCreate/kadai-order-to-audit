import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { LoadingPanel, Skeleton, SkeletonTable, SkeletonText } from '../../components/Skeleton'
import {
  getReconciliation,
  getReport,
  listReports,
  reportDownloadUrl,
  type ColumnKind,
  type DateRange
} from './reportsApi'

function monthDefaults(): Required<DateRange> {
  const now = new Date()
  const month = `${now.getMonth() + 1}`.padStart(2, '0')
  return {
    date_from: `${now.getFullYear()}-${month}-01`,
    date_to: now.toISOString().slice(0, 10)
  }
}

const NUMERIC_KINDS: ColumnKind[] = ['money', 'qty', 'rate', 'int', 'percent', 'variance']

export default function ReportsPage() {
  const { t } = useTranslation()
  const defaults = monthDefaults()
  const [slug, setSlug] = useState('')
  const [dateFrom, setDateFrom] = useState(defaults.date_from)
  const [dateTo, setDateTo] = useState(defaults.date_to)

  const catalog = useQuery({ queryKey: ['reports-catalog'], queryFn: listReports })
  const selected = slug || catalog.data?.[0]?.slug || ''
  const range: DateRange = { date_from: dateFrom, date_to: dateTo }

  const report = useQuery({
    queryKey: ['report', selected, dateFrom, dateTo],
    queryFn: () => getReport(selected, range),
    enabled: selected !== ''
  })
  const reconciliation = useQuery({
    queryKey: ['reconciliation', dateFrom, dateTo],
    queryFn: () => getReconciliation(range)
  })

  const totals = report.data?.totals ?? {}
  const metaEntries = Object.entries(report.data?.meta ?? {}).filter(
    ([, value]) => typeof value !== 'object'
  )

  return (
    <div className="p-4 sm:p-6">
      <h2 className="text-2xl font-semibold text-gray-800">{t('reports.title')}</h2>
      <p className="mt-1 text-sm text-gray-500">{t('reports.subtitle')}</p>

      <div className="mt-4 flex flex-wrap items-end gap-3">
        <div className="min-w-[220px] flex-1">
          <label htmlFor="report-select" className="block text-sm font-medium text-gray-700">
            {t('reports.report')}
          </label>
          <select
            id="report-select"
            value={selected}
            disabled={catalog.isLoading}
            onChange={(event) => setSlug(event.target.value)}
            className="mt-1 block min-h-[44px] w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500"
          >
            {(catalog.data ?? []).map((definition) => (
              <option key={definition.slug} value={definition.slug}>
                {definition.title}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label htmlFor="report-from" className="block text-sm font-medium text-gray-700">
            {t('reports.from')}
          </label>
          <input
            id="report-from"
            type="date"
            value={dateFrom}
            onChange={(event) => setDateFrom(event.target.value)}
            className="mt-1 block min-h-[44px] rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500"
          />
        </div>
        <div>
          <label htmlFor="report-to" className="block text-sm font-medium text-gray-700">
            {t('reports.to')}
          </label>
          <input
            id="report-to"
            type="date"
            value={dateTo}
            onChange={(event) => setDateTo(event.target.value)}
            className="mt-1 block min-h-[44px] rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500"
          />
        </div>
      </div>

      {catalog.isError && (
        <p role="alert" className="mt-4 text-red-700">
          {t('reports.loadError')}
        </p>
      )}

      {(catalog.isLoading || report.isLoading) && (
        <LoadingPanel label={t('reports.loading')} className="mt-6">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <Skeleton className="h-6 w-48" />
            <div className="flex gap-2">
              <Skeleton className="h-11 w-20" />
              <Skeleton className="h-11 w-20" />
              <Skeleton className="h-11 w-20" />
            </div>
          </div>
          <div className="mt-3">
            <SkeletonTable rows={6} columns={5} />
          </div>
        </LoadingPanel>
      )}
      {report.isError && (
        <p role="alert" className="mt-6 text-red-700">
          {t('reports.loadError')}
        </p>
      )}

      {report.data && (
        <section className="mt-6">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h3 className="text-lg font-semibold text-gray-800">{report.data.title}</h3>
            <div className="flex flex-wrap gap-2">
              <a
                href={reportDownloadUrl(report.data.slug, 'csv', range)}
                className="inline-flex min-h-[44px] items-center rounded-md border border-gray-300 bg-white px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"
              >
                {t('reports.csv')}
              </a>
              <a
                href={reportDownloadUrl(report.data.slug, 'excel', range)}
                className="inline-flex min-h-[44px] items-center rounded-md border border-gray-300 bg-white px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"
              >
                {t('reports.excel')}
              </a>
              <a
                href={reportDownloadUrl(report.data.slug, 'pdf', range)}
                className="inline-flex min-h-[44px] items-center rounded-md border border-gray-300 bg-white px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"
              >
                {t('reports.pdf')}
              </a>
            </div>
          </div>

          {metaEntries.length > 0 && (
            <dl className="mt-3 flex flex-wrap gap-x-6 gap-y-1 text-sm text-gray-600">
              {metaEntries.map(([key, value]) => (
                <div key={key} className="flex gap-1">
                  <dt className="font-medium">{t(`reports.meta.${key}`, key)}:</dt>
                  <dd className="tabular-nums">{String(value)}</dd>
                </div>
              ))}
            </dl>
          )}

          <div className="mt-3 overflow-x-auto rounded-lg border border-gray-200 bg-white">
            <table className="min-w-full divide-y divide-gray-200 text-sm">
              <thead className="bg-gray-50">
                <tr>
                  {report.data.columns.map((column) => (
                    <th
                      key={column.key}
                      className={`px-3 py-2 font-semibold text-gray-600 ${
                        NUMERIC_KINDS.includes(column.kind) ? 'text-right' : 'text-left'
                      }`}
                    >
                      {column.label}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {report.data.rows.map((row, index) => (
                  <tr key={index}>
                    {report.data.columns.map((column) => (
                      <td
                        key={column.key}
                        className={`px-3 py-2 ${
                          NUMERIC_KINDS.includes(column.kind)
                            ? 'text-right tabular-nums text-gray-700'
                            : 'text-gray-900'
                        }`}
                      >
                        {row[column.key] ?? ''}
                      </td>
                    ))}
                  </tr>
                ))}
                {report.data.rows.length === 0 && (
                  <tr>
                    <td
                      colSpan={report.data.columns.length}
                      className="px-3 py-4 text-center text-gray-500"
                    >
                      {t('reports.empty')}
                    </td>
                  </tr>
                )}
              </tbody>
              {Object.keys(totals).length > 0 && (
                <tfoot className="bg-gray-50 font-semibold text-gray-900">
                  <tr>
                    {report.data.columns.map((column, index) => (
                      <td
                        key={column.key}
                        className={`px-3 py-2 ${
                          NUMERIC_KINDS.includes(column.kind)
                            ? 'text-right tabular-nums'
                            : 'text-left'
                        }`}
                      >
                        {index === 0 ? t('reports.total') : (totals[column.key] ?? '')}
                      </td>
                    ))}
                  </tr>
                </tfoot>
              )}
            </table>
          </div>
        </section>
      )}

      <section className="mt-8">
        <h3 className="text-lg font-semibold text-gray-800">{t('reports.reconciliation')}</h3>
        <p className="mt-1 text-sm text-gray-500">{t('reports.reconciliationHint')}</p>
        {reconciliation.isLoading && (
          <LoadingPanel label={t('common.loading')} className="mt-3">
            <SkeletonText lines={3} />
          </LoadingPanel>
        )}
        {reconciliation.data && (
          <ul className="mt-3 space-y-2">
            {reconciliation.data.map((check) => (
              <li
                key={check.name}
                className={`flex flex-wrap items-center justify-between gap-2 rounded-lg border p-3 text-sm ${
                  check.passed
                    ? 'border-green-200 bg-green-50 text-green-900'
                    : 'border-red-200 bg-red-50 text-red-900'
                }`}
              >
                <span className="font-medium">{check.name}</span>
                <span className="tabular-nums">
                  {check.passed ? '✓' : '✗'} {check.actual}
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  )
}
