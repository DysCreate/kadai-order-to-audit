import { useMutation } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { apiErrorMessage } from '../../lib/apiError'
import { runBenchmark } from './benchmarkApi'

export default function BenchmarkPage() {
  const { t } = useTranslation()
  const mutation = useMutation({ mutationFn: runBenchmark })
  const result = mutation.data

  return (
    <div className="p-4 sm:p-6">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h2 className="text-2xl font-semibold text-gray-800">{t('benchmark.title')}</h2>
          <p className="mt-1 text-sm text-gray-500">{t('benchmark.subtitle')}</p>
        </div>
        <button
          type="button"
          onClick={() => mutation.mutate()}
          disabled={mutation.isPending}
          className="min-h-[44px] rounded-md bg-blue-800 px-5 py-3 text-base font-medium text-white hover:bg-blue-700 disabled:opacity-50"
        >
          {mutation.isPending ? t('benchmark.running') : t('benchmark.run')}
        </button>
      </div>

      <p className="mt-3 rounded-md border border-gray-200 bg-white p-3 text-sm text-gray-600">
        {t('benchmark.hint')}
      </p>

      {mutation.isError && (
        <p role="alert" className="mt-4 rounded-md border border-red-300 bg-red-50 p-3 text-sm text-red-700">
          {apiErrorMessage(mutation.error, t('benchmark.error'))}
        </p>
      )}

      {result && (
        <section className="mt-5">
          <div
            className={`rounded-lg border p-4 text-lg font-semibold ${
              result.ok
                ? 'border-green-300 bg-green-50 text-green-900'
                : 'border-red-300 bg-red-50 text-red-900'
            }`}
          >
            {result.ok
              ? t('benchmark.allPassed', { passed: result.passed })
              : t('benchmark.failed', { failed: result.failed, passed: result.passed })}
          </div>

          <div className="mt-4 overflow-x-auto rounded-lg border border-gray-200 bg-white">
            <table className="min-w-full divide-y divide-gray-200 text-sm">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-4 py-3 text-left font-semibold text-gray-600">
                    {t('benchmark.check')}
                  </th>
                  <th className="px-4 py-3 text-right font-semibold text-gray-600">
                    {t('benchmark.expected')}
                  </th>
                  <th className="px-4 py-3 text-right font-semibold text-gray-600">
                    {t('benchmark.actual')}
                  </th>
                  <th className="px-4 py-3 text-left font-semibold text-gray-600">
                    {t('benchmark.result')}
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {result.checks.map((check) => (
                  <tr key={check.name} className={check.passed ? '' : 'bg-red-50'}>
                    <td className="px-4 py-2 text-gray-900">{check.name}</td>
                    <td className="px-4 py-2 text-right tabular-nums text-gray-600">
                      {check.expected}
                    </td>
                    <td className="px-4 py-2 text-right tabular-nums text-gray-900">
                      {check.actual}
                    </td>
                    <td className="px-4 py-2">
                      <span
                        className={`inline-flex rounded-full px-2 py-0.5 text-xs font-semibold ${
                          check.passed
                            ? 'bg-green-100 text-green-800'
                            : 'bg-red-100 text-red-800'
                        }`}
                      >
                        {check.passed ? t('benchmark.pass') : t('benchmark.fail')}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </div>
  )
}
