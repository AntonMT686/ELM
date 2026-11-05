// Thin fetch client: same-origin, HttpOnly session cookie, CSRF double-submit header, normalized errors.

export class ApiError extends Error {
  status: number
  code: string
  details: any
  constructor(status: number, code: string, message: string, details?: any) {
    super(message)
    this.status = status
    this.code = code
    this.details = details
  }
}

function csrf(): string {
  const m = document.cookie.match(/(?:^|;\s*)elm_csrf=([^;]+)/)
  return m ? decodeURIComponent(m[1]) : ''
}

type Params = Record<string, string | number | boolean | undefined | null>

function qs(params?: Params) {
  if (!params) return ''
  const u = new URLSearchParams()
  Object.entries(params).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== '') u.set(k, String(v))
  })
  const s = u.toString()
  return s ? `?${s}` : ''
}

let onUnauthorized: (() => void) | null = null
export const setUnauthorizedHandler = (fn: () => void): void => {
  onUnauthorized = fn
}

async function request<T>(method: string, path: string, body?: any, params?: Params): Promise<T> {
  const headers: Record<string, string> = { Accept: 'application/json' }
  let payload: BodyInit | undefined
  if (body instanceof FormData) payload = body
  else if (body !== undefined) {
    headers['Content-Type'] = 'application/json'
    payload = JSON.stringify(body)
  }
  if (method !== 'GET') headers['X-CSRF-Token'] = csrf()
  const res = await fetch(`/api/v1${path}${qs(params)}`, { method, headers, body: payload, credentials: 'same-origin' })
  if (res.status === 401 && !path.startsWith('/auth/login')) onUnauthorized?.()
  const text = await res.text()
  const data = text ? JSON.parse(text) : null
  if (!res.ok) {
    const e = data?.error || {}
    throw new ApiError(res.status, e.code || 'HTTP_' + res.status, e.message || res.statusText, e.details)
  }
  return data as T
}

export const api = {
  get: <T = any>(p: string, params?: Params) => request<T>('GET', p, undefined, params),
  post: <T = any>(p: string, body?: any, params?: Params) => request<T>('POST', p, body ?? {}, params),
  put: <T = any>(p: string, body?: any, params?: Params) => request<T>('PUT', p, body ?? {}, params),
  patch: <T = any>(p: string, body?: any) => request<T>('PATCH', p, body ?? {}),
  del: <T = any>(p: string) => request<T>('DELETE', p),
}

export const fileUrl = (docId: string, revId: string, inline = true, iteration?: number) =>
  `/api/v1/documents/${docId}/revisions/${revId}/file${qs({ inline, iteration })}`

export function errorText(e: unknown): string {
  if (e instanceof ApiError) {
    if (e.details?.errors?.length) return `${e.message} ${e.details.errors.join(' · ')}`
    return e.message
  }
  return (e as Error)?.message || 'Something went wrong'
}
