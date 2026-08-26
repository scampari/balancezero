import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  type Account,
  type PlaidSyncResult,
  listAccountsWithAutoRefresh,
  triggerPlaidSyncWithAutoRefresh,
} from '../api/client'
import { useAuth } from '../auth/AuthContext'
import { AppShell, PageLoading } from '../components/AppShell'

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
  const [isSyncing, setIsSyncing] = useState(false)
  const [syncResult, setSyncResult] = useState<PlaidSyncResult | null>(null)
  const [syncError, setSyncError] = useState<string | null>(null)

  function loadAccounts(token: string) {
    return listAccountsWithAutoRefresh(token, setAccessToken).then((data) => setAccounts(data.accounts))
  }

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

  async function handleSync() {
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
  }

  if (!accounts) return <PageLoading />

  return (
    <AppShell>
      <div className="mb-6 flex items-center justify-between">
        <h1 className="text-xl font-semibold tracking-tight text-(--color-text)">Accounts</h1>
        <button
          type="button"
          onClick={handleSync}
          disabled={isSyncing}
          className="rounded-md bg-(--color-accent) px-3 py-1.5 text-sm font-medium text-(--color-bg) transition-colors hover:bg-(--color-accent-hover) disabled:cursor-not-allowed disabled:opacity-60"
        >
          {isSyncing ? 'Syncing…' : 'Sync now'}
        </button>
      </div>

      {syncError && (
        <div role="alert" className="mb-4 rounded-md border border-(--color-negative)/30 bg-(--color-negative)/10 px-3 py-2 text-sm text-(--color-negative)">
          {syncError}
        </div>
      )}
      {syncResult && (
        <div className="mb-4 rounded-md border border-(--color-accent-border) bg-(--color-accent-bg) px-3 py-2 text-sm text-(--color-text)">
          Synced {syncResult.accounts_synced} account{syncResult.accounts_synced === 1 ? '' : 's'} —{' '}
          {syncResult.transactions_added} new, {syncResult.transactions_modified} updated,{' '}
          {syncResult.transactions_removed} removed.
        </div>
      )}

      {accounts.length === 0 ? (
        <div className="rounded-xl border border-(--color-border) bg-(--color-surface) px-4 py-10 text-center text-sm text-(--color-text-faint)">
          No accounts yet. Connect a bank to get started, or click Sync if you've already connected one.
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
