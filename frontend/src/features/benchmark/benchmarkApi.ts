import apiClient from '../../lib/apiClient'

export interface BenchmarkCheck {
  name: string
  expected: string
  actual: string
  passed: boolean
  detail: string
}

export interface BenchmarkResult {
  ran_at: string
  passed: number
  failed: number
  ok: boolean
  checks: BenchmarkCheck[]
}

export async function runBenchmark(): Promise<BenchmarkResult> {
  const res = await apiClient.post<BenchmarkResult>('/benchmark/run/')
  return res.data
}
