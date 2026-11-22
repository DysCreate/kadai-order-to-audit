import { renderToString } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import NotFoundPage from './NotFoundPage'
import '../i18n'

describe('NotFoundPage', () => {
  it('renders the translated 404 copy and a way home', () => {
    const html = renderToString(
      <MemoryRouter initialEntries={['/missing']}>
        <NotFoundPage />
      </MemoryRouter>
    )

    expect(html).toContain('404')
    expect(html).toContain('Page not found')
    expect(html).toContain('does not exist or has moved')
    expect(html).toContain('href="/"')
    expect(html).toContain('Go to home')
  })
})
