import { useCallback, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  type Account,
  type PlaidInstitution,
  type PlaidSyncResult,
  getPlaidStatusWithAutoRefresh,
  listAccountsWithAutoRefresh,
  removePlaidItemWithAutoRefresh,
  setAccountDebtPayoffWithAutoRefresh,
  triggerPlaidSyncWithAutoRefresh,
} from '../api/client'
import { useAuth } from '../auth/AuthContext'
import { AppShell, PageLoading } from '../components/AppShell'
import { ConnectBankButton } from '../components/ConnectBankButton'

function formatMoney(value: string): string {
  return Number(value).toLocaleString('en-US', { style: 'currency', currency: 'USD' })
}

function formatDate(value: string): string {
  return new Date(value).toLocaleString('en-US', { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })
}

// A liability's balance is stored negative — money you owe, not money you have.
function isLiability(account: Account): boolean {
  return account.type === 'credit' || account.type === 'loan'
}

// Human label for an account's kind. Prefer Plaid's specific `subtype`
// ("checking", "credit card"), fall back to the coarse `type`.
function accountTypeLabel(account: Account): string | null {
  const raw = account.subtype ?? account.type
  if (!raw) return null
  return raw.replace(/\b\w/g, (c) => c.toUpperCase())
}

const UNLINKED_GROUP_KEY = 'unlinked'

interface AccountGroup {
  key: string
  name: string
  accounts: Account[]
}

// Group the account cards by linked institution, in the institutions-list
// order, with any demo/manual/unlinked accounts last under "Not linked".
function groupAccountsByInstitution(accounts: Account[], institutions: PlaidInstitution[]): AccountGroup[] {
  const groups: AccountGroup[] = []
  for (const institution of institutions) {
    const owned = accounts.filter((account) => account.plaid_item_id === institution.id)
    if (owned.length > 0) {
      groups.push({ key: String(institution.id), name: institution.institution_name, accounts: owned })
    }
  }
  const unlinked = accounts.filter(
    (account) => account.plaid_item_id === null || !institutions.some((i) => i.id === account.plaid_item_id),
  )
  if (unlinked.length > 0) {
    groups.push({ key: UNLINKED_GROUP_KEY, name: 'Not linked', accounts: unlinked })
  }
  return groups
}

export function AccountsPage() {
  const { accessToken, setAccessToken, isAuthChecked } = useAuth()
  const navigate = useNavigate()
  const [accounts, setAccounts] = useState<Account[] | null>(null)
  const [institutions, setInstitutions] = useState<PlaidInstitution[]>([])
  const [isSyncing, setIsSyncing] = useState(false)
  const [syncResult, setSyncResult] = useState<PlaidSyncResult | null>(null)
  const [syncError, setSyncError] = useState<string | null>(null)
  const [removingId, setRemovingId] = useState<number | null>(null)
  const [debtPayoffPendingId, setDebtPayoffPendingId] = useState<number | null>(null)

  const loadAccounts = useCallback(
    (token: string) =>
      Promise.all([
        listAccountsWithAutoRefresh(token, setAccessToken),
        getPlaidStatusWithAutoRefresh(token, setAccessToken),
      ]).then(([accountsData, statusData]) => {
        setAccounts(accountsData.accounts)
        setInstitutions(statusData.items)
      }),
    [setAccessToken],
  )

  useEffect(() => {
    let cancelled = false

    if (!isAuthChecked) return
    if (!accessToken) {
      navigate('/login', { replace: true })
      return
    }

    loadAccounts(accessToken).catch(() => {
      if (!cancelled) {
        setAccessToken(null)
        navigate('/login', { replace: true })
      }
    })

    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [accessToken, isAuthChecked, navigate, setAccessToken])

  const runSync = useCallback(async () => {
    if (!accessToken) return
    setIsSyncing(true)
    setSyncError(null)
    setSyncResult(null)
    try {
      const result = await triggerPlaidSyncWithAutoRefresh(accessToken, setAccessToken)
      setSyncResult(result)
      await loadAccounts(accessToken)
    } catch (err) {
      setSyncError(err instanceof Error ? err.message : 'Sync failed. Please try again.')
    } finally {
      setIsSyncing(false)
    }
  }, [accessToken, setAccessToken, loadAccounts])

  // A fresh connection has no transactions locally yet — pull them right away
  // so the page isn't empty after linking a bank.
  const handleConnected = useCallback(() => {
    void runSync()
  }, [runSync])

  const handleRemove = useCallback(
    async (itemId: number) => {
      if (!accessToken) return
      setRemovingId(itemId)
      setSyncError(null)
      try {
        await removePlaidItemWithAutoRefresh(accessToken, setAccessToken, itemId)
        await loadAccounts(accessToken)
      } catch (err) {
        setSyncError(err instanceof Error ? err.message : 'Could not remove that institution.')
      } finally {
        setRemovingId(null)
      }
    },
    [accessToken, setAccessToken, loadAccounts],
  )

  const handleToggleDebtPayoff = useCallback(
    async (accountId: number, next: boolean) => {
      if (!accessToken) return
      setDebtPayoffPendingId(accountId)
      setSyncError(null)
      try {
        await setAccountDebtPayoffWithAutoRefresh(accessToken, setAccessToken, accountId, next)
        await loadAccounts(accessToken)
      } catch (err) {
        setSyncError(err instanceof Error ? err.message : 'Could not update that account.')
      } finally {
        setDebtPayoffPendingId(null)
      }
    },
    [accessToken, setAccessToken, loadAccounts],
  )

  if (!accounts) return <PageLoading />

  const hasItems = institutions.length > 0
  const failedItems = syncResult?.items.filter((item) => item.status === 'error') ?? []

  return (
    <AppShell>
      <div className="mb-6 flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-xl font-semibold tracking-tight text-(--color-text)">Accounts</h1>
        <div className="flex flex-wrap items-center gap-2">
          {hasItems && (
            <button
              type="button"
              onClick={runSync}
              disabled={isSyncing}
              className="rounded-md bg-(--color-accent) px-3 py-1.5 text-sm font-medium text-(--color-on-accent) transition-colors hover:bg-(--color-accent-hover) disabled:cursor-not-allowed disabled:opacity-60"
            >
              {isSyncing ? 'Syncing…' : 'Sync now'}
            </button>
          )}
          <ConnectBankButton hasItems={hasItems} onConnected={handleConnected} />
        </div>
      </div>

      {hasItems && (
        <div className="mb-6 divide-y divide-(--color-border) overflow-hidden rounded-xl border border-(--color-border)">
          {institutions.map((institution) => (
            <div
              key={institution.id}
              data-institution={institution.institution_name}
              className="flex items-center justify-between bg-(--color-surface) px-4 py-3"
            >
              <div>
                <p className="text-sm font-medium text-(--color-text)">{institution.institution_name}</p>
                <p className="mt-0.5 text-xs text-(--color-text-faint)">
                  {institution.account_count} account{institution.account_count === 1 ? '' : 's'}
                  {institution.last_synced ? ` — synced ${formatDate(institution.last_synced)}` : ' — never synced'}
                </p>
              </div>
              <button
                type="button"
                onClick={() => handleRemove(institution.id)}
                disabled={removingId === institution.id}
                className="rounded-md px-2.5 py-1 text-xs font-medium text-(--color-text-faint) transition-colors hover:bg-(--color-surface-hover) hover:text-(--color-negative) disabled:cursor-not-allowed disabled:opacity-60"
              >
                {removingId === institution.id ? 'Removing…' : 'Remove'}
              </button>
            </div>
          ))}
        </div>
      )}

      {syncError && (
        <div role="alert" className="mb-4 rounded-md border border-(--color-negative)/30 bg-(--color-negative)/10 px-3 py-2 text-sm text-(--color-negative)">
          {syncError}
        </div>
      )}
      {syncResult && (
        <div className="mb-4 rounded-md border border-(--color-accent-border) bg-(--color-accent-bg) px-3 py-2 text-sm text-(--color-text)">
          Synced {syncResult.totals.transactions_added} new, {syncResult.totals.transactions_modified} updated,{' '}
          {syncResult.totals.transactions_removed} removed across {syncResult.items.length} institution
          {syncResult.items.length === 1 ? '' : 's'}.
          {failedItems.length > 0 && (
            <span className="mt-1 block text-(--color-negative)">
              Couldn’t sync: {failedItems.map((item) => item.institution_name).join(', ')}.
            </span>
          )}
        </div>
      )}

      {accounts.length === 0 ? (
        <div className="rounded-xl border border-(--color-border) bg-(--color-surface) px-4 py-10 text-center text-sm text-(--color-text-faint)">
          {hasItems
            ? 'Connected, but no accounts yet. Click Sync now to pull them in.'
            : 'No accounts yet. Connect a bank to get started.'}
        </div>
      ) : (
        <div className="space-y-6">
          {groupAccountsByInstitution(accounts, institutions).map((group) => (
            <div key={group.key} data-account-group={group.name}>
              <h2 className="mb-2 text-xs font-semibold uppercase tracking-wide text-(--color-text-faint)">
                {group.name}
              </h2>
              <div className="grid gap-3 sm:grid-cols-2">
                {group.accounts.map((account) => {
                  const typeLabel = accountTypeLabel(account)
                  return (
                    <div
                      key={account.id}
                      data-account-type={account.type ?? ''}
                      className="rounded-xl border border-(--color-border) bg-(--color-surface) p-4"
                    >
                      <div className="flex items-baseline justify-between gap-2">
                        <p className="text-sm font-medium text-(--color-text)">{account.name}</p>
                        {typeLabel && (
                          <span className="shrink-0 text-xs text-(--color-text-faint)">{typeLabel}</span>
                        )}
                      </div>
                      <p
                        className={`tabular-nums mt-2 text-2xl font-semibold ${
                          isLiability(account) ? 'text-(--color-negative)' : 'text-(--color-text)'
                        }`}
                      >
                        {formatMoney(account.balance)}
                      </p>
                      {account.available_balance !== null && account.available_balance !== account.balance && (
                        <p className="tabular-nums mt-0.5 text-xs text-(--color-text-muted)">
                          {formatMoney(account.available_balance)} available
                        </p>
                      )}
                      <p className="mt-3 text-xs text-(--color-text-faint)">
                        {account.balance_date ? `Updated ${formatDate(account.balance_date)}` : 'Never synced'}
                      </p>
                      {account.type === 'credit' && (
                        <div className="mt-3 border-t border-(--color-border) pt-3">
                          <div className="flex items-center justify-between gap-3">
                            <span className="text-xs font-medium text-(--color-text)">Paying this off</span>
                            <button
                              type="button"
                              role="switch"
                              aria-checked={account.debt_payoff}
                              aria-label="Paying this off"
                              disabled={debtPayoffPendingId === account.id}
                              onClick={() =>
                                void handleToggleDebtPayoff(account.id, !account.debt_payoff)
                              }
                              className={`relative inline-flex h-5 w-9 shrink-0 items-center rounded-full transition-colors disabled:opacity-60 ${
                                account.debt_payoff ? 'bg-(--color-accent)' : 'bg-(--color-border)'
                              }`}
                            >
                              <span
                                className={`inline-block h-4 w-4 transform rounded-full bg-(--color-surface) shadow transition-transform ${
                                  account.debt_payoff ? 'translate-x-4' : 'translate-x-0.5'
                                }`}
                              />
                            </button>
                          </div>
                          <p className="mt-1 text-xs text-(--color-text-faint)">
                            Its payments count as spending in a category you choose, instead of the
                            automatic payment envelope.
                          </p>
                        </div>
                      )}
                    </div>
                  )
                })}
              </div>
            </div>
          ))}
        </div>
      )}
    </AppShell>
  )
}
