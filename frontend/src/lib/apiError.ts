interface ApiErrorBody {
  detail?: string
  code?: string
}

/** Read the machine-readable error body the backend returns, else a fallback. */
export function apiErrorMessage(error: unknown, fallback: string): string {
  const body = (error as { response?: { data?: ApiErrorBody } })?.response?.data
  return body?.detail ?? body?.code ?? fallback
}
