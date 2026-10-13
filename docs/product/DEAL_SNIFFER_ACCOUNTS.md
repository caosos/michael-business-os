# DealSniffer accounts and Google sign-in

DealSniffer currently remains usable in local-owner mode with no account configuration. The account boundary now isolates each authenticated user's Marketplace preferences, including their city/ZIP/radius, saved items, hidden items, filters, bid tracking, and suggestion feedback.

Google sign-in is intentionally separate from source accounts. DealSniffer will request only `openid email profile` for sign-in. It will not ask for a Facebook password, auction-site password, Gmail access, or provider access token. Source accounts remain the user's accounts.

## Google web OAuth configuration

`dealsniffers.com` is the intended production domain. DNS, HTTPS, and Google configuration still require deployment proof. The expected web callback is `https://dealsniffers.com/auth/google/callback`; that exact URI must be registered in Google Cloud and supplied as the redirect environment value. The code does not treat domain purchase alone as proof that the callback is live.

Configure all four values together; a partial or unsafe configuration stops startup instead of silently weakening authentication:

- `MBOS_GOOGLE_CLIENT_ID`
- `MBOS_GOOGLE_CLIENT_SECRET`
- `MBOS_GOOGLE_REDIRECT_URI` — exact Google-authorized callback; HTTPS except for loopback development
- `MBOS_SESSION_SECRET` — at least 32 random bytes

Optional: `MBOS_ACCOUNT_DATA_DIR` selects the private account/profile root. Profile files contain the Google subject, email, and display name only. OAuth access/refresh tokens are neither returned to the application nor stored.

When all four values are valid, the public routes are:

- `/home` — customer homepage (`/` on the configured public host)
- `/privacy` — public privacy policy
- `/terms` — public terms
- `/auth/google/start` — state + nonce + PKCE authorization start
- `/auth/google/callback` — exact registered callback
- `/auth/logout` — POST-only session removal

The callback exchanges the one-time code directly with Google's fixed HTTPS token endpoint. It verifies the returned ID token locally against Google's fixed HTTPS JWKS endpoint, including the RS256 signature, issuer, audience/authorized party, expiration, issue time, nonce, subject, and verified email. State/nonce/PKCE data and sessions are HMAC-signed with short expirations and HttpOnly, SameSite cookies; production cookies are Secure. Only `openid email profile` is requested. Public-host requests without a valid session cannot enter customer data routes, and authenticated public users cannot open local operator routes. Loopback requests retain the existing local-owner behavior.

With no OAuth variables, Google sign-in reports **NOT CONFIGURED** and performs no provider request. The EliteDesk's loopback Marketplace continues to work in local-owner mode.

## Still external deployment work

The implemented flow does not make DNS, HTTPS, the Google Cloud client, or Google's consent-screen verification exist. Those must be configured and then proven through the public domain. No live client secret is committed, and the tests make no Google network calls.

Vendor-alert email ingestion and any later source-account connection are separate, explicit permissions. They must not be bundled into Google sign-in.
