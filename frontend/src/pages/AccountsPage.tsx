import { useCallback, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  type Account,
  type PlaidInstitution,
  type PlaidSyncResult,
  getPlaidStatusWithAutoRefresh,
  listAccountsWithAutoRefresh,
  removePlaidItemWithAutoRefresh,
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

export function AccountsPage() {
  const { accessToken, setAccessToken, isAuthChecked } = useAuth()
  const navigate = useNavigate()
  const [accounts, setAccounts] = useState<Account[] | null>(null)
  const [institutions, setInstitutions] = useState<PlaidInstitution[]>([])
  const [isSyncing, setIsSyncing] = useState(false)
  const [syncResult, setSyncResult] = useState<PlaidSyncResult | null>(null)
  const [syncError, setSyncError] = useState<string | null>(null)
  const [removingId, setRemovingId] = useState<number | null>(null)

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

  if (!accounts) return <PageLoading />

  const hasItems = institutions.length > 0
  const failedItems = syncResult?.items.filter((item) => item.status === 'error') ?? []

  return (
    <AppShell>
      <div className="mb-6 flex items-center justify-between">
        <h1 className="text-xl font-semibold tracking-tight text-(--color-text)">Accounts</h1>
        <div className="flex items-center gap-2">
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
        <div className="grid gap-3 sm:grid-cols-2">
          {accounts.map((account) => (
            <div key={account.id} className="rounded-xl border border-(--color-border) bg-(--color-surface) p-4">
              <p className="text-sm font-medium text-(--color-text)">{account.name}</p>
              <p className="tabular-nums mt-2 text-2xl font-semibold text-(--color-text)">
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
            </div>
          ))}
        </div>
      )}
    </AppShell>
  )
}
