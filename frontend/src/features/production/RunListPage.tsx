import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import { listRuns, type RunState } from './productionApi'

const STATE_STYLES: Record<RunState, string> = {
  DRAFT: 'bg-gray-100 text-gray-700',
  ISSUED: 'bg-amber-100 text-amber-800',
  COMPLETED: 'bg-green-100 text-green-800'
}

export default function RunListPage() {
  const { t } = useTranslation()
  const { data, isLoading, isError } = useQuery({
    queryKey: ['production-runs'],
    queryFn: listRuns
  })

  return (
    <div className="p-4 sm:p-6">
      <h2 className="text-2xl font-semibold text-gray-800">{t('production.title')}</h2>
      <p className="mt-1 text-sm text-gray-500">{t('production.subtitle')}</p>

      {isLoading && <p className="mt-6 text-gray-500">{t('production.loading')}</p>}
      {isError && (
        <p role="alert" className="mt-6 text-red-700">
          {t('production.loadError')}
        </p>
      )}

      {data && data.length === 0 && (
        <p className="mt-6 text-gray-500">{t('production.empty')}</p>
      )}

      {data && data.length > 0 && (
        <ul className="mt-6 space-y-3">
          {data.map((run) => (
            <li key={run.id}>
              <Link
                to={`/production/runs/${run.id}`}
                className="flex min-h-[64px] flex-col gap-2 rounded-lg border border-gray-200 bg-white p-4 shadow-sm transition-colors hover:border-blue-400 sm:flex-row sm:items-center sm:justify-between"
              >
                <div>
                  <div className="text-lg font-semibold text-gray-900">
                    {t('production.runLabel', { id: run.id })} · {run.product_name}
                  </div>
                  <div className="text-sm text-gray-500">
                    {t('production.batches', { batches: run.batches })} ·{' '}
                    {t('production.plannedOutput', { qty: run.planned_output_qty })}
                  </div>
                </div>
                <span
                  className={`inline-flex w-fit items-center rounded-full px-3 py-1 text-sm font-medium ${STATE_STYLES[run.state]}`}
                >
                  {t(`production.states.${run.state}`)}
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
