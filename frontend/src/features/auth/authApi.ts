import apiClient from '../../lib/apiClient'

export interface User {
  id: number
  username: string
  role: string
}

export async function login(username: string, password: string): Promise<User> {
  const res = await apiClient.post<{ user: User }>('/accounts/login/', { username, password })
  return res.data.user
}

export async function logout(): Promise<void> {
  await apiClient.post('/accounts/logout/')
}

export async function getMe(): Promise<User> {
  const res = await apiClient.get<{ user: User }>('/accounts/me/')
  return res.data.user
}
