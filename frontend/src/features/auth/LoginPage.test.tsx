import { renderToString } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import LoginPage from './LoginPage'
import i18n from '../../i18n'

vi.mock('./AuthContext', () => ({
  useAuth: () => ({ setUser: () => {} })
}))

function renderPage() {
  return renderToString(
    <MemoryRouter>
      <LoginPage />
    </MemoryRouter>
  )
}

describe('LoginPage', () => {
  afterEach(async () => {
    await i18n.changeLanguage('en')
  })

  it('offers English and Tamil on the sign-in screen', () => {
    const html = renderPage()

    expect(html).toContain('aria-label="Language"')
    expect(html).toContain('>English<')
    expect(html).toContain('>தமிழ்<')
  })

  it('renders the sign-in copy in the selected language', async () => {
    await i18n.changeLanguage('ta')
    const html = renderPage()

    expect(html).toContain('உள்நுழை')
    expect(html).toContain('பயனர்பெயர்')
  })
})
