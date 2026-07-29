export type BusinessModule =
  | 'workbench'
  | 'requests'
  | 'jobs'
  | 'screening'
  | 'candidates'
  | 'candidate-process'
  | 'interviews'
  | 'hiring'
  | 'talent'
  | 'analytics'
  | 'settings'

export function businessModuleForPath(pathname: string): BusinessModule {
  if (pathname === '/workbench' || pathname.startsWith('/workbench/')) return 'workbench'
  if (pathname.startsWith('/recruitment-requests')) return 'requests'
  if (pathname.startsWith('/candidates')) return 'candidates'
  if (pathname.startsWith('/offers')) return 'hiring'
  if (pathname.startsWith('/onboardings')) return 'hiring'
  if (pathname.startsWith('/analytics')) return 'analytics'
  if (pathname.startsWith('/settings/')) return 'settings'
  if (pathname.endsWith('/batches') || pathname.endsWith('/results') || pathname.endsWith('/compare')) {
    return 'screening'
  }
  if (
    pathname.endsWith('/pipeline') ||
    (pathname.endsWith('/history') && pathname.includes('/documents/'))
  ) {
    return 'candidate-process'
  }
  if (
    pathname.endsWith('/interview-plan') ||
    pathname.endsWith('/interview-reports') ||
    pathname.endsWith('/interview-report') ||
    pathname.endsWith('/interview-schedule') ||
    pathname.includes('/interview-evaluations/')
  ) {
    return 'interviews'
  }
  return 'jobs'
}

export function safeWorkbenchReturnPath(value: string | null): string | null {
  if (!value || !value.startsWith('/') || value.startsWith('//')) return null
  try {
    const resolved = new URL(value, window.location.origin)
    if (resolved.origin !== window.location.origin || resolved.pathname !== '/workbench') {
      return null
    }
    return `${resolved.pathname}${resolved.search}${resolved.hash}`
  } catch {
    return null
  }
}

export function withWorkbenchReturnTo(targetPath: string, returnTo: string): string {
  if (!targetPath.startsWith('/') || targetPath.startsWith('//')) return '/workbench'
  try {
    const target = new URL(targetPath, window.location.origin)
    if (target.origin !== window.location.origin) return '/workbench'
    target.searchParams.set('returnTo', safeWorkbenchReturnPath(returnTo) ?? '/workbench')
    return `${target.pathname}${target.search}${target.hash}`
  } catch {
    return '/workbench'
  }
}

export function jobIdFromPath(pathname: string): string | null {
  const jobId = pathname.match(/^\/jobs\/([^/]+)/)?.[1]
  return jobId && jobId !== 'new' ? jobId : null
}

export function defaultPathForModule(module: BusinessModule, jobId: string): string {
  const encodedJobId = encodeURIComponent(jobId)
  if (module === 'screening') return `/jobs/${encodedJobId}/batches`
  if (module === 'candidate-process') return `/jobs/${encodedJobId}/pipeline`
  if (module === 'interviews') return `/jobs/${encodedJobId}/interview-plan`
  return `/jobs/${encodedJobId}`
}
