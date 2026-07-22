import { createContext, useContext } from 'react'

import type { AuthUser, LoginCredentials } from '../api/client'

export interface AuthContextValue {
  user: AuthUser | null
  isLoading: boolean
  isLoggingIn: boolean
  isLoggingOut: boolean
  error: Error | null
  login: (credentials: LoginCredentials) => Promise<AuthUser>
  logout: () => Promise<void>
  retry: () => Promise<void>
}

export const AuthContext = createContext<AuthContextValue | null>(null)

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext)
  if (!context) {
    throw new Error('useAuth 必须在 AuthProvider 内使用')
  }
  return context
}
