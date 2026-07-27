import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, type ReactNode } from 'react'

import {
  changePassword as changePasswordRequest,
  fetchCurrentUser,
  login as loginRequest,
  logout as logoutRequest,
  AUTH_UNAUTHORIZED_EVENT,
  type AuthUser,
  type ChangePasswordInput,
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
  const changePasswordMutation = useMutation({ mutationFn: changePasswordRequest })

  useEffect(() => {
    function handleUnauthorized() {
      queryClient.setQueryData(currentUserQueryKey, null)
    }
    window.addEventListener(AUTH_UNAUTHORIZED_EVENT, handleUnauthorized)
    return () => window.removeEventListener(AUTH_UNAUTHORIZED_EVENT, handleUnauthorized)
  }, [queryClient])

  async function login(credentials: LoginCredentials): Promise<AuthUser> {
    const user = await loginMutation.mutateAsync(credentials)
    queryClient.setQueryData(currentUserQueryKey, user)
    return user
  }

  async function logout(): Promise<void> {
    await logoutMutation.mutateAsync()
    queryClient.setQueryData(currentUserQueryKey, null)
  }

  async function changePassword(payload: ChangePasswordInput): Promise<AuthUser> {
    const user = await changePasswordMutation.mutateAsync(payload)
    queryClient.setQueryData(currentUserQueryKey, user)
    return user
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
        isChangingPassword: changePasswordMutation.isPending,
        error: currentUser.error instanceof Error ? currentUser.error : null,
        login,
        logout,
        changePassword,
        retry,
      }}
    >
      {children}
    </AuthContext.Provider>
  )
}
