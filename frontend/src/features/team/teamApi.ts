import apiClient from '../../lib/apiClient'

export interface TeamMember {
  id: number
  username: string
  email: string
  role: string
  date_joined: string
}

export interface PendingInvitation {
  id: number
  email: string
  role: string
  created_at: string
  expires_at: string
}

export interface Team {
  members: TeamMember[]
  invitations: PendingInvitation[]
  invitable_roles: string[]
}

export async function getTeam(): Promise<Team> {
  const res = await apiClient.get<Team>('/accounts/team/')
  return res.data
}

export async function inviteMember(input: { email: string; role: string }): Promise<PendingInvitation> {
  const res = await apiClient.post<PendingInvitation>('/accounts/team/invitations/', input)
  return res.data
}
