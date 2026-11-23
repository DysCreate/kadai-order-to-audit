import { useEffect, useMemo, useState, type FormEvent } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { Link, useNavigate } from 'react-router-dom'
import { LoadingPanel, SkeletonCardList } from '../../components/Skeleton'
import { useAuth } from '../auth/AuthContext'
import { apiErrorMessage } from '../../lib/apiError'
import {
  createRun,
  listBoms,
  listRuns,
  type Bom,
  type RunState
} from './productionApi'

const STATE_STYLES: Record<RunState, string> = {
  DRAFT: 'bg-gray-100 text-gray-700',
  ISSUED: 'bg-amber-100 text-amber-800',
  COMPLETED: 'bg-green-100 text-green-800'
}

const PLAN_ROLES = ['production', 'admin', 'owner']

/** Keep the newest BOM version for each finished-goods product. */
function latestBomsByProduct(boms: Bom[]): Bom[] {
  const latest = new Map<number, Bom>()
  for (const bom of boms) {
    const current = latest.get(bom.product_id)
    if (!current || bom.version > current.version) latest.set(bom.product_id, bom)
  }
  return [...latest.values()].sort((a, b) => a.product_name.localeCompare(b.product_name))
}

export default function RunListPage() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { user } = useAuth()
  const canPlan = PLAN_ROLES.includes(user?.role ?? '')

  const { data, isLoading, isError } = useQuery({
    queryKey: ['production-runs'],
    queryFn: listRuns
  })

  const boms = useQuery({
    queryKey: ['production-boms'],
    queryFn: listBoms,
    enabled: canPlan
  })

  const products = useMemo(
    () => latestBomsByProduct(boms.data ?? []),
    [boms.data]
  )

  const [productId, setProductId] = useState('')
  const [batches, setBatches] = useState('1')
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (products.length === 0) return
    if (!products.some((bom) => String(bom.product_id) === productId)) {
      setProductId(String(products[0].product_id))
    }
  }, [products, productId])

  const createMutation = useMutation({
    mutationFn: () => createRun(Number(productId), batches),
    onSuccess: (run) => {
      setError(null)
      queryClient.invalidateQueries({ queryKey: ['production-runs'] })
      navigate(`/production/runs/${run.id}`)
    },
    onError: (failure) => setError(apiErrorMessage(failure, t('production.newRun.error')))
  })

  function handleCreate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError(null)
    createMutation.mutate()
  }

  const selected = products.find((bom) => String(bom.product_id) === productId)

  return (
    <div className="p-4 sm:p-6">
      <h2 className="text-2xl font-semibold text-gray-800">{t('production.title')}</h2>
      <p className="mt-1 text-sm text-gray-500">{t('production.subtitle')}</p>

      {canPlan && (
        <form
          onSubmit={handleCreate}
          className="mt-5 rounded-lg border border-gray-200 bg-white p-4 shadow-sm"
        >
          <h3 className="text-lg font-semibold text-gray-800">{t('production.newRun.title')}</h3>
          <p className="mt-1 text-sm text-gray-500">{t('production.newRun.hint')}</p>

          {boms.isLoading && (
            <p className="mt-3 text-sm text-gray-500">{t('common.loading')}</p>
          )}
          {boms.isError && (
            <p role="alert" className="mt-3 text-sm text-red-700">
              {t('production.newRun.bomError')}
            </p>
          )}
          {boms.data && products.length === 0 && (
            <p className="mt-3 rounded border border-amber-300 bg-amber-50 p-3 text-sm text-amber-800">
              {t('production.newRun.noBoms')}
            </p>
          )}

          {products.length > 0 && (
            <div className="mt-3 flex flex-col gap-3 sm:flex-row sm:items-end">
              <div className="flex-1">
                <label
                  htmlFor="run-product"
                  className="block text-sm font-medium text-gray-700"
                >
                  {t('production.newRun.product')}
                </label>
                <select
                  id="run-product"
                  value={productId}
                  onChange={(event) => setProductId(event.target.value)}
                  className="mt-1 block min-h-[44px] w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500"
                >
                  {products.map((bom) => (
                    <option key={bom.product_id} value={bom.product_id}>
                      {t('production.newRun.productOption', {
                        product: bom.product_name,
                        version: bom.version,
                        output: bom.batch_output_qty
                      })}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label
                  htmlFor="run-batches"
                  className="block text-sm font-medium text-gray-700"
                >
                  {t('production.newRun.batches')}
                </label>
                <input
                  id="run-batches"
                  type="number"
                  inputMode="decimal"
                  min="0.001"
                  step="0.001"
                  value={batches}
                  onChange={(event) => setBatches(event.target.value)}
                  className="mt-1 block min-h-[44px] w-40 rounded-md border-gray-300 text-right text-lg font-semibold shadow-sm focus:border-blue-500 focus:ring-blue-500"
                />
              </div>
              <button
                type="submit"
                disabled={
                  createMutation.isPending ||
                  productId === '' ||
                  selected === undefined ||
                  Number(batches) <= 0
                }
                className="min-h-[44px] rounded-md bg-blue-800 px-5 py-3 font-medium text-white hover:bg-blue-700 disabled:opacity-50"
              >
                {createMutation.isPending ? '…' : t('production.newRun.submit')}
              </button>
            </div>
          )}

          {error && (
            <p role="alert" className="mt-3 rounded border border-red-300 bg-red-50 p-2 text-sm text-red-700">
              {error}
            </p>
          )}
        </form>
      )}

      {isLoading && (
        <LoadingPanel label={t('production.loading')} className="mt-6">
          <SkeletonCardList count={3} />
        </LoadingPanel>
      )}
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
