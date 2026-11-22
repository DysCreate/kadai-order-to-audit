import type { ReactNode } from 'react'

/**
 * Shared loading placeholders.
 *
 * Skeletons are decorative: the wrapper announces the loading state once to
 * assistive technology while the pulsing blocks stay hidden from the tree.
 * Animation is disabled for users who prefer reduced motion.
 */
export function LoadingPanel({
  label,
  children,
  className = ''
}: {
  label: string
  children: ReactNode
  className?: string
}) {
  return (
    <div role="status" aria-live="polite" aria-busy="true" className={className}>
      <span className="sr-only">{label}</span>
      <div aria-hidden="true">{children}</div>
    </div>
  )
}

export function Skeleton({ className = '' }: { className?: string }) {
  return (
    <div
      className={`animate-pulse rounded-md bg-gray-200 motion-reduce:animate-none ${className}`}
    />
  )
}

export function SkeletonText({ lines = 3, className = '' }: { lines?: number; className?: string }) {
  return (
    <div className={`space-y-2 ${className}`}>
      {Array.from({ length: lines }, (_, index) => (
        <Skeleton
          key={index}
          className={`h-4 ${index === lines - 1 ? 'w-2/3' : 'w-full'}`}
        />
      ))}
    </div>
  )
}

export function SkeletonCard({ className = '' }: { className?: string }) {
  return (
    <div className={`rounded-lg border border-gray-200 bg-white p-4 shadow-sm ${className}`}>
      <div className="flex items-start justify-between gap-4">
        <Skeleton className="h-5 w-40 max-w-[60%]" />
        <Skeleton className="h-6 w-20 rounded-full" />
      </div>
      <Skeleton className="mt-3 h-4 w-56 max-w-full" />
      <Skeleton className="mt-2 h-4 w-24" />
    </div>
  )
}

export function SkeletonCardList({ count = 3 }: { count?: number }) {
  return (
    <div className="space-y-3">
      {Array.from({ length: count }, (_, index) => (
        <SkeletonCard key={index} />
      ))}
    </div>
  )
}

export function SkeletonTable({ rows = 5, columns = 4 }: { rows?: number; columns?: number }) {
  return (
    <div className="overflow-hidden rounded-lg border border-gray-200 bg-white">
      <div className="flex gap-3 border-b border-gray-200 bg-gray-50 px-3 py-3">
        {Array.from({ length: columns }, (_, index) => (
          <Skeleton key={index} className="h-4 flex-1" />
        ))}
      </div>
      {Array.from({ length: rows }, (_, row) => (
        <div
          key={row}
          className="flex gap-3 border-b border-gray-100 px-3 py-3 last:border-b-0"
        >
          {Array.from({ length: columns }, (_, column) => (
            <Skeleton
              key={column}
              className={`h-4 flex-1 ${column === 0 ? '' : 'max-w-[25%]'}`}
            />
          ))}
        </div>
      ))}
    </div>
  )
}

/** Header + summary cards + table, for route-level data screens. */
export function SkeletonDetailPage({ label }: { label: string }) {
  return (
    <LoadingPanel label={label} className="p-4 sm:p-6">
      <Skeleton className="h-8 w-64 max-w-full" />
      <Skeleton className="mt-2 h-4 w-80 max-w-full" />
      <div className="mt-6 grid gap-4 lg:grid-cols-2">
        <div className="rounded-lg border border-gray-200 bg-white p-4">
          <Skeleton className="h-5 w-32" />
          <SkeletonText lines={4} className="mt-3" />
        </div>
        <div className="rounded-lg border border-gray-200 bg-white p-4">
          <Skeleton className="h-5 w-32" />
          <SkeletonText lines={4} className="mt-3" />
        </div>
      </div>
      <div className="mt-6">
        <SkeletonTable rows={4} columns={4} />
      </div>
    </LoadingPanel>
  )
}
