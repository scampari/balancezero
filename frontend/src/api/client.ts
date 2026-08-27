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

// Invite-only account creation. On success the server logs the new user
// straight in — same {access_token} body + refresh cookie as login().
export async function register(
  username: string,
  password: string,
  inviteCode: string,
  email?: string,
): Promise<{ accessToken: string }> {
  const payload: Record<string, string> = { username, password, invite_code: inviteCode }
  if (email) payload.email = email
  const res = await request('/signup', { method: 'POST', body: JSON.stringify(payload) })
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
  months_remaining: number
  funded: string
  needed_this_month: string
  progress: string
}

export interface BudgetCategory {
  id: number
  name: string
  parent_id: number | null
  position: number
  archived: boolean
  allocated_this_month: string
  spent_this_month: string
  available: string
  target: CategoryTarget | null
}

export interface BudgetTotals {
  budgeted: string
  spent: string
  available: string
}

export interface Budget {
  month: string
  ready_to_assign: string
  totals: BudgetTotals
  categories: BudgetCategory[]
  archived_categories: BudgetCategory[]
}

export interface CategoryPatch {
  name?: string
  parent_id?: number | null
  archived?: boolean
  position?: number
}

export async function patchCategory(
  accessToken: string,
  categoryId: number,
  patch: CategoryPatch,
): Promise<{ id: number; name: string; parent_id: number | null; archived: boolean; position: number }> {
  const res = await request(
    `/categories/${categoryId}`,
    { method: 'PATCH', body: JSON.stringify(patch) },
    accessToken,
  )
  await throwIfError(res)
  return res.json()
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
  // Our own PlaidItem row id (not a Plaid identifier). Null for demo/manual
  // accounts and for accounts whose institution was unlinked.
  plaid_item_id: number | null
}

export async function listAccounts(accessToken: string): Promise<{ accounts: Account[] }> {
  const res = await request('/accounts', { method: 'GET' }, accessToken)
  await throwIfError(res)
  return res.json()
}

interface PlaidSyncCounts {
  accounts_synced: number
  transactions_added: number
  transactions_modified: number
  transactions_removed: number
}

export interface PlaidSyncItemResult extends PlaidSyncCounts {
  id: number
  institution_name: string
  status: 'ok' | 'error'
  error?: string
}

// One /plaid/sync call fans out over every linked institution. `ok` is true
// only when every one succeeded; individual failures show up as items with
// status 'error' (the whole call still returns 200 as long as one succeeded).
export interface PlaidSyncResult {
  items: PlaidSyncItemResult[]
  totals: PlaidSyncCounts
  ok: boolean
}

export interface PlaidInstitution {
  id: number
  institution_name: string
  institution_id: string | null
  last_synced: string | null
  account_count: number
}

export async function triggerPlaidSync(accessToken: string): Promise<PlaidSyncResult> {
  const res = await request('/plaid/sync', { method: 'POST' }, accessToken)
  await throwIfError(res)
  return res.json()
}

export async function getPlaidStatus(accessToken: string): Promise<{ items: PlaidInstitution[] }> {
  const res = await request('/plaid/status', { method: 'GET' }, accessToken)
  await throwIfError(res)
  return res.json()
}

export async function removePlaidItem(accessToken: string, itemId: number): Promise<{ status: string }> {
  const res = await request(`/plaid/items/${itemId}`, { method: 'DELETE' }, accessToken)
  await throwIfError(res)
  return res.json()
}

// Step 1 of the Plaid Link flow: the backend mints a short-lived link_token
// (its own server-to-server call to Plaid), which the browser hands to the
// Plaid Link widget to open it.
export async function createPlaidLinkToken(accessToken: string): Promise<{ link_token: string }> {
  const res = await request('/plaid/link-token', { method: 'POST' }, accessToken)
  await throwIfError(res)
  return res.json()
}

// Step 2: after the user completes Link, the widget returns a public_token to
// the browser; the backend exchanges it for the permanent (encrypted-at-rest)
// access_token and stores a PlaidItem. The public_token is opaque and
// single-use — safe to send here. The institution name/id come from Plaid
// Link's onSuccess metadata so the linked-institutions list can label the row.
export async function connectPlaid(
  accessToken: string,
  publicToken: string,
  institution?: { name?: string | null; id?: string | null },
): Promise<{ status: string; item: PlaidInstitution }> {
  const body: Record<string, string> = { public_token: publicToken }
  if (institution?.name) body.institution_name = institution.name
  if (institution?.id) body.institution_id = institution.id
  const res = await request('/plaid/connect', { method: 'POST', body: JSON.stringify(body) }, accessToken)
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

export function patchCategoryWithAutoRefresh(
  accessToken: string,
  onTokenRefreshed: (token: string) => void,
  categoryId: number,
  patch: CategoryPatch,
): Promise<{ id: number; name: string; parent_id: number | null; archived: boolean; position: number }> {
  return withAutoRefresh(
    (token) => patchCategory(token, categoryId, patch),
    accessToken,
    onTokenRefreshed,
  )
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
): Promise<{ items: PlaidInstitution[] }> {
  return withAutoRefresh((token) => getPlaidStatus(token), accessToken, onTokenRefreshed)
}

export function createPlaidLinkTokenWithAutoRefresh(
  accessToken: string,
  onTokenRefreshed: (token: string) => void,
): Promise<{ link_token: string }> {
  return withAutoRefresh((token) => createPlaidLinkToken(token), accessToken, onTokenRefreshed)
}

export function connectPlaidWithAutoRefresh(
  accessToken: string,
  onTokenRefreshed: (token: string) => void,
  publicToken: string,
  institution?: { name?: string | null; id?: string | null },
): Promise<{ status: string; item: PlaidInstitution }> {
  return withAutoRefresh(
    (token) => connectPlaid(token, publicToken, institution),
    accessToken,
    onTokenRefreshed,
  )
}

export function removePlaidItemWithAutoRefresh(
  accessToken: string,
  onTokenRefreshed: (token: string) => void,
  itemId: number,
): Promise<{ status: string }> {
  return withAutoRefresh((token) => removePlaidItem(token, itemId), accessToken, onTokenRefreshed)
}
