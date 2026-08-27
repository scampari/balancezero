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

export type TargetType = 'monthly' | 'yearly' | 'custom'

export interface CategoryTarget {
  target_type: TargetType
  target_amount: string
  target_date: string | null
  monthly_target_amount: string
}

export interface BudgetCategory {
  id: number
  name: string
  parent_id: number | null
  allocated_this_month: string
  available: string
  target: CategoryTarget | null
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

export interface TransactionEntry {
  id: number
  account_id: number
  category_id: number | null
  category_name: string | null
  posted_at: string
  amount: string
  description: string
  pending: boolean
  is_income: boolean
}

export interface TransactionsResponse {
  month: string
  transactions: TransactionEntry[]
}

export async function getTransactions(accessToken: string, month?: string): Promise<TransactionsResponse> {
  const qs = month ? `?month=${encodeURIComponent(month)}` : ''
  const res = await request(`/transactions${qs}`, { method: 'GET' }, accessToken)
  await throwIfError(res)
  return res.json()
}

export interface TransactionPatchResult {
  id: number
  category_id: number | null
  category_name: string | null
  is_income: boolean
}

export async function patchTransactionCategory(
  accessToken: string,
  transactionId: number,
  categoryId: number | null,
): Promise<TransactionPatchResult> {
  const res = await request(
    `/transactions/${transactionId}`,
    { method: 'PATCH', body: JSON.stringify({ category_id: categoryId }) },
    accessToken,
  )
  await throwIfError(res)
  return res.json()
}

// Marks a transaction "To Be Budgeted" — the server clears any category
// (is_income and category_id are mutually exclusive).
export async function markTransactionIncome(
  accessToken: string,
  transactionId: number,
): Promise<TransactionPatchResult> {
  const res = await request(
    `/transactions/${transactionId}`,
    { method: 'PATCH', body: JSON.stringify({ is_income: true, category_id: null }) },
    accessToken,
  )
  await throwIfError(res)
  return res.json()
}

export async function createCategory(
  accessToken: string,
  name: string,
  parentId?: number | null,
): Promise<{ id: number; name: string; parent_id: number | null }> {
  const body: { name: string; parent_id?: number } = { name }
  if (parentId != null) body.parent_id = parentId
  const res = await request('/categories', { method: 'POST', body: JSON.stringify(body) }, accessToken)
  await throwIfError(res)
  return res.json()
}

export async function setAllocation(
  accessToken: string,
  categoryId: number,
  month: string,
  amount: string,
): Promise<{ category_id: number; month: string; allocated_amount: string }> {
  const res = await request(
    `/categories/${categoryId}/allocations`,
    { method: 'POST', body: JSON.stringify({ month, amount }) },
    accessToken,
  )
  await throwIfError(res)
  return res.json()
}

export interface SetTargetInput {
  target_type: TargetType
  target_amount: string
  target_date?: string
}

export async function setCategoryTarget(
  accessToken: string,
  categoryId: number,
  input: SetTargetInput,
): Promise<CategoryTarget & { id: number; category_id: number }> {
  const res = await request(
    `/categories/${categoryId}/target`,
    { method: 'POST', body: JSON.stringify(input) },
    accessToken,
  )
  await throwIfError(res)
  return res.json()
}

export interface Account {
  id: number
  name: string
  currency: string
  balance: string
  available_balance: string | null
  balance_date: string | null
}

export async function listAccounts(accessToken: string): Promise<{ accounts: Account[] }> {
  const res = await request('/accounts', { method: 'GET' }, accessToken)
  await throwIfError(res)
  return res.json()
}

export interface PlaidSyncResult {
  accounts_synced: number
  transactions_added: number
  transactions_modified: number
  transactions_removed: number
}

export async function triggerPlaidSync(accessToken: string): Promise<PlaidSyncResult> {
  const res = await request('/plaid/sync', { method: 'POST' }, accessToken)
  await throwIfError(res)
  return res.json()
}

export async function getPlaidStatus(accessToken: string): Promise<{ connected: boolean }> {
  const res = await request('/plaid/status', { method: 'GET' }, accessToken)
  await throwIfError(res)
  return res.json()
}

/**
 * Wraps any authenticated call so an expired access token refreshes once and
 * retries — structurally capped at one retry (no recursion, no loop), unlike
 * a dependency-array-triggered re-run which could repeat indefinitely if the
 * server keeps 401ing for a reason refresh() can't fix.
 */
async function withAutoRefresh<T>(
  call: (accessToken: string) => Promise<T>,
  accessToken: string,
  onTokenRefreshed: (token: string) => void,
): Promise<T> {
  try {
    return await call(accessToken)
  } catch (err) {
    if (err instanceof ApiError && err.status === 401) {
      const refreshed = await refresh()
      if (refreshed) {
        onTokenRefreshed(refreshed.accessToken)
        return call(refreshed.accessToken)
      }
    }
    throw err
  }
}

export function getBudgetWithAutoRefresh(
  accessToken: string,
  onTokenRefreshed: (token: string) => void,
  month?: string,
): Promise<Budget> {
  return withAutoRefresh((token) => getBudget(token, month), accessToken, onTokenRefreshed)
}

export function getTransactionsWithAutoRefresh(
  accessToken: string,
  onTokenRefreshed: (token: string) => void,
  month?: string,
): Promise<TransactionsResponse> {
  return withAutoRefresh((token) => getTransactions(token, month), accessToken, onTokenRefreshed)
}

export function patchTransactionCategoryWithAutoRefresh(
  accessToken: string,
  onTokenRefreshed: (token: string) => void,
  transactionId: number,
  categoryId: number | null,
): Promise<TransactionPatchResult> {
  return withAutoRefresh(
    (token) => patchTransactionCategory(token, transactionId, categoryId),
    accessToken,
    onTokenRefreshed,
  )
}

export function markTransactionIncomeWithAutoRefresh(
  accessToken: string,
  onTokenRefreshed: (token: string) => void,
  transactionId: number,
): Promise<TransactionPatchResult> {
  return withAutoRefresh(
    (token) => markTransactionIncome(token, transactionId),
    accessToken,
    onTokenRefreshed,
  )
}

export function setCategoryTargetWithAutoRefresh(
  accessToken: string,
  onTokenRefreshed: (token: string) => void,
  categoryId: number,
  input: SetTargetInput,
): Promise<CategoryTarget & { id: number; category_id: number }> {
  return withAutoRefresh(
    (token) => setCategoryTarget(token, categoryId, input),
    accessToken,
    onTokenRefreshed,
  )
}

export function createCategoryWithAutoRefresh(
  accessToken: string,
  onTokenRefreshed: (token: string) => void,
  name: string,
  parentId?: number | null,
): Promise<{ id: number; name: string; parent_id: number | null }> {
  return withAutoRefresh((token) => createCategory(token, name, parentId), accessToken, onTokenRefreshed)
}

export function setAllocationWithAutoRefresh(
  accessToken: string,
  onTokenRefreshed: (token: string) => void,
  categoryId: number,
  month: string,
  amount: string,
): Promise<{ category_id: number; month: string; allocated_amount: string }> {
  return withAutoRefresh(
    (token) => setAllocation(token, categoryId, month, amount),
    accessToken,
    onTokenRefreshed,
  )
}

export function listAccountsWithAutoRefresh(
  accessToken: string,
  onTokenRefreshed: (token: string) => void,
): Promise<{ accounts: Account[] }> {
  return withAutoRefresh((token) => listAccounts(token), accessToken, onTokenRefreshed)
}

export function triggerPlaidSyncWithAutoRefresh(
  accessToken: string,
  onTokenRefreshed: (token: string) => void,
): Promise<PlaidSyncResult> {
  return withAutoRefresh((token) => triggerPlaidSync(token), accessToken, onTokenRefreshed)
}

export function getPlaidStatusWithAutoRefresh(
  accessToken: string,
  onTokenRefreshed: (token: string) => void,
): Promise<{ connected: boolean }> {
  return withAutoRefresh((token) => getPlaidStatus(token), accessToken, onTokenRefreshed)
}
