import i18n from 'i18next'
import { initReactI18next } from 'react-i18next'
import en from './locales/en.json'
import ta from './locales/ta.json'

function readStoredLanguage(): string {
  try {
    return window.localStorage?.getItem('kadai.lang') ?? 'en'
  } catch {
    // Storage can be unavailable in tests and strict privacy modes.
    return 'en'
  }
}

const storedLanguage = typeof window === 'undefined' ? 'en' : readStoredLanguage()

i18n
  .use(initReactI18next)
  .init({
    resources: {
      en: { translation: en },
      ta: { translation: ta },
    },
    lng: storedLanguage === 'ta' ? 'ta' : 'en',
    fallbackLng: 'en',
    interpolation: {
      escapeValue: false,
    },
  })

export default i18n
