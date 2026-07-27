import type { AuthUser } from '../api/client'

export function canManageRecruitment(user: AuthUser | null): boolean {
  return user?.roles.some((role) => role === 'administrator' || role === 'recruiter') ?? false
}

export function canViewSensitiveRecruitmentData(user: AuthUser | null): boolean {
  return canManageRecruitment(user)
}
