export type BusinessModule =
  | 'workbench'
  | 'jobs'
  | 'screening'
  | 'candidate-process'
  | 'interviews'
  | 'talent'
  | 'analytics'
  | 'settings'

export function businessModuleForPath(pathname: string): BusinessModule {
  if (pathname.endsWith('/batches') || pathname.endsWith('/results') || pathname.endsWith('/compare')) {
    return 'screening'
  }
  if (
    pathname.endsWith('/pipeline') ||
    (pathname.endsWith('/history') && pathname.includes('/documents/'))
  ) {
    return 'candidate-process'
  }
  if (pathname.endsWith('/interview-plan') || pathname.endsWith('/interview-schedule')) {
    return 'interviews'
  }
  return 'jobs'
}

export function jobIdFromPath(pathname: string): string | null {
  return pathname.match(/^\/jobs\/([^/]+)/)?.[1] ?? null
}
