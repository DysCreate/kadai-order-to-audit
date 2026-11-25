type ApiErrorBody = Record<string, unknown>

/** Read the machine-readable error body the backend returns, else a fallback. */
export function apiErrorMessage(error: unknown, fallback: string): string {
  const body = (error as { response?: { data?: ApiErrorBody } })?.response?.data
  if (!body) return fallback

  if (typeof body.detail === 'string') return body.detail
  if (typeof body.code === 'string') return body.code

  for (const value of Object.values(body)) {
    if (typeof value === 'string') return value
    if (Array.isArray(value) && typeof value[0] === 'string') return value[0]
  }
  return fallback
}
