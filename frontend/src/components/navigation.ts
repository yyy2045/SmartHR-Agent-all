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
  if (
    pathname.endsWith('/interview-plan') ||
    pathname.endsWith('/interview-schedule') ||
    pathname.includes('/interview-evaluations/')
  ) {
    return 'interviews'
  }
  return 'jobs'
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
  return `/jobs/${encodedJobId}/edit`
}
