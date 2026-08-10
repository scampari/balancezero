const API_BASE = '/api'

export class ApiError extends Error {
  status: number

  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

async function request(path: string, options: RequestInit = {}, accessToken?: string): Promise<Response> {
  const headers = new Headers(options.headers)
  headers.set('Content-Type', 'application/json')
  if (accessToken) headers.set('Authorization', `Bearer ${accessToken}`)
  // credentials: 'include' sends the httpOnly refresh cookie on /refresh and /logout.
  return fetch(`${API_BASE}${path}`, { ...options, headers, credentials: 'include' })
}

async function errorMessage(res: Response): Promise<string> {
  const body = await res.json().catch(() => ({}))
  return body.error ?? 'Something went wrong. Please try again.'
}

export async function login(username: string, password: string): Promise<{ accessToken: string }> {
  const res = await request('/login', { method: 'POST', body: JSON.stringify({ username, password }) })
  if (!res.ok) throw new ApiError(res.status, await errorMessage(res))
  const body = await res.json()
  return { accessToken: body.access_token }
}

export async function refresh(): Promise<{ accessToken: string } | null> {
  const res = await request('/refresh', { method: 'POST' })
  if (!res.ok) return null
  const body = await res.json()
  return { accessToken: body.access_token }
}

export async function logout(accessToken: string): Promise<void> {
  await request('/logout', { method: 'POST' }, accessToken)
}

export interface BudgetCategory {
  id: number
  name: string
  allocated_this_month: string
  available: string
}

export interface Budget {
  month: string
  ready_to_assign: string
  categories: BudgetCategory[]
}

export async function getBudget(accessToken: string, month?: string): Promise<Budget> {
  const qs = month ? `?month=${encodeURIComponent(month)}` : ''
  const res = await request(`/budget${qs}`, { method: 'GET' }, accessToken)
  if (!res.ok) throw new ApiError(res.status, await errorMessage(res))
  return res.json()
}
