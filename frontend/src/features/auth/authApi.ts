import apiClient from '../../lib/apiClient'

export interface Organization {
  id: number
  name: string
}

export interface User {
  id: number
  username: string
  role: string
  organization?: Organization
}

export interface InvitationPreview {
  email: string
  role: string
  organization_name: string
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

export async function registerOrganization(input: {
  organization_name: string
  username: string
  email: string
  password: string
}): Promise<User> {
  const res = await apiClient.post<{ user: User }>('/accounts/register/', input)
  return res.data.user
}

export async function getInvitation(token: string): Promise<InvitationPreview> {
  const res = await apiClient.get<InvitationPreview>(`/accounts/invitations/${token}/`)
  return res.data
}

export async function acceptInvitation(
  token: string,
  input: { username: string; password: string }
): Promise<User> {
  const res = await apiClient.post<{ user: User }>(
    `/accounts/invitations/${token}/accept/`,
    input
  )
  return res.data.user
}
