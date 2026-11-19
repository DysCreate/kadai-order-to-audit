import { describe, it, expect, vi, beforeEach } from 'vitest'
import apiClient from '../../lib/apiClient'
import { login, logout, getMe } from './authApi'

vi.mock('../../lib/apiClient')

describe('authApi', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('login posts credentials and returns user', async () => {
    const mockUser = { id: 1, username: 'admin', role: 'admin' }
    vi.mocked(apiClient.post).mockResolvedValueOnce({ data: { user: mockUser } })

    const user = await login('admin', 'admin')
    expect(apiClient.post).toHaveBeenCalledWith('/accounts/login/', {
      username: 'admin',
      password: 'admin',
    })
    expect(user).toEqual(mockUser)
  })

  it('logout posts to logout endpoint', async () => {
    vi.mocked(apiClient.post).mockResolvedValueOnce({ data: {} })
    await logout()
    expect(apiClient.post).toHaveBeenCalledWith('/accounts/logout/')
  })

  it('getMe requests me endpoint and returns user', async () => {
    const mockUser = { id: 2, username: 'salesman_a', role: 'salesman' }
    vi.mocked(apiClient.get).mockResolvedValueOnce({ data: { user: mockUser } })

    const user = await getMe()
    expect(apiClient.get).toHaveBeenCalledWith('/accounts/me/')
    expect(user).toEqual(mockUser)
  })
})
