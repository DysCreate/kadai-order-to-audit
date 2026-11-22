import { renderToString } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { LoadingPanel, Skeleton, SkeletonTable } from './Skeleton'

describe('Skeleton', () => {
  it('announces loading once and hides the placeholders from assistive technology', () => {
    const html = renderToString(
      <LoadingPanel label="Loading widgets…">
        <Skeleton className="h-4 w-24" />
        <SkeletonTable rows={2} columns={3} />
      </LoadingPanel>
    )

    expect(html).toContain('role="status"')
    expect(html).toContain('aria-busy="true"')
    expect(html).toContain('Loading widgets…')
    expect(html).toContain('aria-hidden="true"')
    expect(html).toContain('motion-reduce:animate-none')
  })
})
