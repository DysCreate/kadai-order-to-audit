import { Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'

export default function NotFoundPage() {
  const { t } = useTranslation()

  return (
    <section className="flex min-h-[60vh] items-center justify-center p-6">
      <div className="max-w-md text-center">
        <p className="text-sm font-semibold uppercase tracking-widest text-blue-700">404</p>
        <h2 className="mt-2 text-2xl font-semibold text-gray-900">{t('notFound.title')}</h2>
        <p className="mt-2 text-sm text-gray-500">{t('notFound.subtitle')}</p>
        <Link
          to="/"
          className="mt-6 inline-flex min-h-[44px] items-center rounded-md bg-blue-800 px-5 py-2 text-sm font-semibold text-white hover:bg-blue-700"
        >
          {t('notFound.home')}
        </Link>
      </div>
    </section>
  )
}
