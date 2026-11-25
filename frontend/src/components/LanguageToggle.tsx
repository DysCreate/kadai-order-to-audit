import { useTranslation } from 'react-i18next'

type Language = 'en' | 'ta'

export default function LanguageToggle({ className = '' }: { className?: string }) {
  const { t, i18n } = useTranslation()
  const language: Language = i18n.language.startsWith('ta') ? 'ta' : 'en'

  function changeLanguage(next: Language) {
    void i18n.changeLanguage(next)
    try {
      localStorage.setItem('kadai.lang', next)
    } catch {
      // Storage can be unavailable in strict privacy modes.
    }
    document.documentElement.lang = next
  }

  return (
    <div
      role="group"
      aria-label={t('language.label')}
      className={`inline-flex rounded-md border border-gray-300 bg-white p-1 shadow-sm ${className}`}
    >
      {(['en', 'ta'] as const).map((value) => (
        <button
          key={value}
          type="button"
          aria-pressed={language === value}
          onClick={() => changeLanguage(value)}
          className={`min-h-[44px] rounded px-3 text-sm font-medium transition-colors ${
            language === value ? 'bg-blue-800 text-white' : 'text-gray-700 hover:bg-gray-100'
          }`}
        >
          {t(value === 'en' ? 'language.english' : 'language.tamil')}
        </button>
      ))}
    </div>
  )
}
