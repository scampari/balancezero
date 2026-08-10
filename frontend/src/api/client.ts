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

async function throwIfError(res: Response): Promise<void> {
  if (res.ok) return
  const body = await res.json().catch(() => ({}))
  throw new ApiError(res.status, body.error ?? 'Something went wrong. Please try again.')
}

export async function login(username: string, password: string): Promise<{ accessToken: string }> {
  const res = await request('/login', { method: 'POST', body: JSON.stringify({ username, password }) })
  await throwIfError(res)
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
  await throwIfError(res)
  return res.json()
}

/**
 * getBudget, but on an expired access token it refreshes once and retries —
 * structurally capped at one retry (no recursion, no loop), unlike a
 * dependency-array-triggered re-run which could repeat indefinitely if the
 * server keeps 401ing for a reason refresh() can't fix.
 */
export async function getBudgetWithAutoRefresh(
  accessToken: string,
  onTokenRefreshed: (token: string) => void,
  month?: string,
): Promise<Budget> {
  try {
    return await getBudget(accessToken, month)
  } catch (err) {
    if (err instanceof ApiError && err.status === 401) {
      const refreshed = await refresh()
      if (refreshed) {
        onTokenRefreshed(refreshed.accessToken)
        return getBudget(refreshed.accessToken, month)
      }
    }
    throw err
  }
}
