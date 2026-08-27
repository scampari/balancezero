import { useCallback, useEffect, useState } from 'react'
import { usePlaidLink, type PlaidLinkOnSuccessMetadata } from 'react-plaid-link'
import { connectPlaidWithAutoRefresh, createPlaidLinkTokenWithAutoRefresh } from '../api/client'
import { useAuth } from '../auth/AuthContext'

// Drives the two-step Plaid Link flow from the browser:
//   1. click -> backend mints a link_token
//   2. link_token opens the Plaid Link widget; on success the widget hands
//      back a public_token, which we POST to the backend to exchange for the
//      permanent access_token (stored encrypted, server-side only).
// The access_token never touches the browser -- same guarantee as SimpleFIN.
//
// OAuth institutions (Chase, BofA, ...) can't finish inside the widget: Link
// redirects the whole browser tab to the bank, the bank redirects back to the
// registered redirect_uri (PLAID_REDIRECT_URI on the backend) with an
// ?oauth_state_id=... query param, and Link must be re-initialized with the
// SAME link_token plus receivedRedirectUri to resume. React state doesn't
// survive that full-page navigation, so the link_token is parked in
// localStorage across it -- see storeLinkToken below for why that's an
// acceptable, scoped exception to this app's "no tokens in web storage" rule.

// The link_token is short-lived (hours), single-institution, and useless on
// its own -- it only lets an in-flight Link session resume. It is NOT the JWT
// access token (memory-only, by design) or the Plaid access_token (backend,
// encrypted). Persisting it across the OAuth redirect is Plaid's own
// documented guidance, and localStorage is the option they name; we scope it
// to one key and delete it the moment the flow ends (success or exit).
const OAUTH_LINK_TOKEN_KEY = 'bz.plaid.oauthLinkToken'

function readStoredLinkToken(): string | null {
  try {
    return window.localStorage.getItem(OAUTH_LINK_TOKEN_KEY)
  } catch {
    return null
  }
}

function storeLinkToken(token: string): void {
  try {
    window.localStorage.setItem(OAUTH_LINK_TOKEN_KEY, token)
  } catch {
    // Private mode / storage disabled: OAuth resume won't work, but the
    // non-OAuth path (no redirect) still completes fine.
  }
}

function clearStoredLinkToken(): void {
  try {
    window.localStorage.removeItem(OAUTH_LINK_TOKEN_KEY)
  } catch {
    // ignore
  }
}

const isOAuthRedirectBack =
  typeof window !== 'undefined' && new URLSearchParams(window.location.search).has('oauth_state_id')

export function ConnectBankButton({
  hasItems,
  onConnected,
}: {
  hasItems: boolean
  onConnected: () => void
}) {
  const { accessToken, setAccessToken } = useAuth()
  // On an OAuth redirect back, rehydrate the parked link_token so Link can
  // resume; otherwise start empty and fetch a fresh one on click.
  const [linkToken, setLinkToken] = useState<string | null>(() =>
    isOAuthRedirectBack ? readStoredLinkToken() : null,
  )
  const [isWorking, setIsWorking] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const endFlow = useCallback(() => {
    clearStoredLinkToken()
    setLinkToken(null)
    if (isOAuthRedirectBack) {
      // Drop ?oauth_state_id=... so a manual refresh doesn't re-enter the
      // resume path with a now-spent token.
      window.history.replaceState({}, '', window.location.pathname)
    }
  }, [])

  const onSuccess = useCallback(
    async (publicToken: string | null, metadata: PlaidLinkOnSuccessMetadata) => {
      if (!accessToken || !publicToken) return
      setIsWorking(true)
      setError(null)
      try {
        await connectPlaidWithAutoRefresh(accessToken, setAccessToken, publicToken, {
          name: metadata.institution?.name,
          id: metadata.institution?.institution_id,
        })
        onConnected()
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Could not finish connecting. Please try again.')
      } finally {
        endFlow()
        setIsWorking(false)
      }
    },
    [accessToken, setAccessToken, onConnected, endFlow],
  )

  const { open, ready } = usePlaidLink({
    token: linkToken,
    onSuccess,
    onExit: () => endFlow(),
    // Pass receivedRedirectUri ONLY on the OAuth return render -- Link errors
    // if it's set on a normal open.
    ...(isOAuthRedirectBack ? { receivedRedirectUri: window.location.href } : {}),
  })

  // usePlaidLink can't be opened until it has processed the token, so we set
  // the token (on click, or from storage on OAuth return) and open once ready.
  useEffect(() => {
    if (linkToken && ready) open()
  }, [linkToken, ready, open])

  async function handleClick() {
    if (!accessToken) return
    setIsWorking(true)
    setError(null)
    try {
      const { link_token } = await createPlaidLinkTokenWithAutoRefresh(accessToken, setAccessToken)
      storeLinkToken(link_token)
      setLinkToken(link_token)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not start Plaid. Please try again.')
    } finally {
      setIsWorking(false)
    }
  }

  const label = hasItems ? 'Connect another bank' : 'Connect a bank'
  const busy = isWorking || (linkToken !== null && !ready)

  return (
    <div className="flex flex-col items-end gap-1">
      <button
        type="button"
        onClick={handleClick}
        disabled={busy}
        className={
          hasItems
            ? 'rounded-md border border-(--color-border) px-3 py-1.5 text-sm font-medium text-(--color-text-muted) transition-colors hover:bg-(--color-surface-hover) hover:text-(--color-text) disabled:cursor-not-allowed disabled:opacity-60'
            : 'rounded-md bg-(--color-accent) px-3 py-1.5 text-sm font-medium text-(--color-on-accent) transition-colors hover:bg-(--color-accent-hover) disabled:cursor-not-allowed disabled:opacity-60'
        }
      >
        {busy ? 'Opening Plaid…' : label}
      </button>
      {error && (
        <span role="alert" className="text-xs text-(--color-negative)">
          {error}
        </span>
      )}
    </div>
  )
}
