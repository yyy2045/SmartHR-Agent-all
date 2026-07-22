import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import type { ReactNode } from 'react'

import {
  fetchCurrentUser,
  login as loginRequest,
  logout as logoutRequest,
  type AuthUser,
  type LoginCredentials,
} from '../api/client'
import { AuthContext } from './context'

const currentUserQueryKey = ['auth', 'current-user'] as const

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient()
  const currentUser = useQuery({
    queryKey: currentUserQueryKey,
    queryFn: fetchCurrentUser,
    retry: false,
    staleTime: Number.POSITIVE_INFINITY,
  })
  const loginMutation = useMutation({ mutationFn: loginRequest })
  const logoutMutation = useMutation({ mutationFn: logoutRequest })

  async function login(credentials: LoginCredentials): Promise<AuthUser> {
    const user = await loginMutation.mutateAsync(credentials)
    queryClient.setQueryData(currentUserQueryKey, user)
    return user
  }

  async function logout(): Promise<void> {
    await logoutMutation.mutateAsync()
    queryClient.setQueryData(currentUserQueryKey, null)
  }

  async function retry(): Promise<void> {
    await currentUser.refetch()
  }

  return (
    <AuthContext.Provider
      value={{
        user: currentUser.data ?? null,
        isLoading: currentUser.isPending,
        isLoggingIn: loginMutation.isPending,
        isLoggingOut: logoutMutation.isPending,
        error: currentUser.error instanceof Error ? currentUser.error : null,
        login,
        logout,
        retry,
      }}
    >
      {children}
    </AuthContext.Provider>
  )
}
