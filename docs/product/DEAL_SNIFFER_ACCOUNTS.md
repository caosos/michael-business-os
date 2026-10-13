# DealSniffer accounts foundation

DealSniffer currently remains usable in local-owner mode with no account configuration. The account boundary now isolates each authenticated user's Marketplace preferences, including their city/ZIP/radius, saved items, hidden items, filters, bid tracking, and suggestion feedback.

Google sign-in is intentionally separate from source accounts. DealSniffer will request only `openid email profile` for sign-in. It will not ask for a Facebook password, auction-site password, Gmail access, or provider access token. Source accounts remain the user's accounts.

## Google web OAuth configuration

`dealsniffers.com` is the intended production domain. Registration is in progress, so DNS and HTTPS are not yet proven and Google OAuth remains **NOT CONFIGURED**. Once the domain is serving HTTPS, the expected web callback is `https://dealsniffers.com/auth/google/callback`; that exact URI must be registered in Google Cloud and supplied as the redirect environment value. The code does not treat domain purchase alone as proof that the callback is live.

Configure all four values together; a partial or unsafe configuration stops startup instead of silently weakening authentication:

- `MBOS_GOOGLE_CLIENT_ID`
- `MBOS_GOOGLE_CLIENT_SECRET`
- `MBOS_GOOGLE_REDIRECT_URI` — exact Google-authorized callback; HTTPS except for loopback development
- `MBOS_SESSION_SECRET` — at least 32 random bytes

Optional: `MBOS_ACCOUNT_DATA_DIR` selects the private account/profile root. Profile files contain the Google subject, email, and display name only. OAuth access/refresh tokens are not accepted or stored by this foundation.

## Deliberately not enabled yet

No sign-in button or OAuth callback is exposed until the public DealSniffer domain, exact callback URI, Google Cloud OAuth client, and consent-screen configuration exist. The future callback must verify Google's ID-token signature, issuer, audience, expiration, nonce, and state before calling `google_account`, saving a profile, and issuing a signed session.

Vendor-alert email ingestion and any later source-account connection are separate, explicit permissions. They must not be bundled into Google sign-in.
