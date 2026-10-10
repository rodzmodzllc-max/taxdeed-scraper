# Sign in with Google, Apple and Microsoft

Added 2026-10-10. Supabase Auth runs the whole flow (`signInWithOAuth`). TAXACQ
stores no provider secret: client ids and secrets live in the Supabase
dashboard only.

## What the code does

- **Buttons.** `public/app.js` `renderOAuthButtons()` adds "Continue with
  Google / Apple / Microsoft" above the email form, only for the providers
  listed in `config.js` `oauthProviders`. The list ships empty. A provider
  that is not enabled in Supabase answers with a raw error page, so a button
  must never appear before its provider is switched on.
- **Return page.** A click calls
  `sb.auth.signInWithOAuth({ provider, options: { redirectTo } })`.
  `redirectTo` is `recoveryRedirectUrl()`, the same exact, allowlisted
  `/index.html` the password-reset link uses. No new Redirect URL entry and
  no wildcard are needed. A visitor who started on another state's page lands
  on the Florida page and switches state from the header.
- **Microsoft.** Supabase's id is `azure`, and the call asks for the `email`
  scope, which Supabase requires for Azure.
- **Approval is unchanged.** On return, supabase-js reads the session from the
  URL and emits `SIGNED_IN`, and `checkApprovalAndEnter()` decides access as
  for any account. A first-time provider sign-in creates the account:
  - `handle_new_user` inserts `profiles` with `approved = false`;
  - migration 030 queues the operator alert;
  - the person sees the pending screen.
- **Missing details.** A provider shares an email and, at most, a name. The
  pending screen (`renderPendingDetails()`) asks for the sign-up form's five
  details, pre-filling the first and last name from the provider's name, and
  saves them with `auth.updateUser({ data })`. That is the same place the
  sign-up form and Edit profile keep them. Saving grants nothing.
- **Cancelled or refused sign-in.** The visitor returns with `?error=...`.
  The sign-in screen says which provider's sign-in did not complete and
  removes the error from the address. The raw provider text is never shown.

## Owner steps (outside the repository)

Do each provider separately. Add its id to `oauthProviders` only after its
Supabase switch is on and one test sign-in has worked.

The Supabase callback URL for every provider is:

    https://cqnnnvpbocafuvpzfbzu.supabase.co/auth/v1/callback

### Google (`google`)

1. In Google Cloud Console, open APIs & Services → OAuth consent screen. Set
   it to External, with app name TAXACQ, the support email, and the authorised
   domain `taxacq.com`. Scopes: `openid`, `email`, `profile`.
2. Under Credentials, create an OAuth client ID of type Web application, with
   the callback URL above as an Authorised redirect URI.
3. In Supabase → Authentication → Sign In / Providers → Google, paste the
   client ID and secret, then enable it.

### Apple (`apple`)

This needs a paid Apple Developer Program membership.

1. Under Certificates, Identifiers & Profiles, create an App ID with "Sign in
   with Apple", then a **Services ID**. Its identifier is the client id. For
   web sign-in, set the domain to `cqnnnvpbocafuvpzfbzu.supabase.co` and the
   return URL to the callback above.
2. Create a Sign in with Apple **key** and download the `.p8` file. Generate
   the client secret (a JWT) from the Team ID, Key ID, Services ID and `.p8`.
   Supabase's Apple guide documents this. Apple limits that secret to six
   months, so **renew it before it expires**, or Apple sign-in stops.
3. Paste the Services ID and the generated secret into Supabase → Providers →
   Apple, then enable it.
4. **E-mail to "Hide My Email" addresses.** A person who hides their email
   gets an `@privaterelay.appleid.com` address. The approval email reaches
   them only if `taxacq.com` (the sending domain) is registered under
   Services → Sign in with Apple for Email Communication. That relay also
   requires SPF / DKIM for the domain, which Resend already uses.
5. Apple shares the person's name only on their first sign-in. If it is
   missing, the pending screen asks for it.

### Microsoft (`azure`)

1. In the Microsoft Entra admin center, open App registrations → New
   registration:
   - Supported account types: "Accounts in any organizational directory and
     personal Microsoft accounts" (both work and personal accounts);
   - Redirect URI (Web): the callback above.
2. Under Certificates & secrets, create a client secret. Note its expiry, and
   **renew it before it expires**.
3. In Supabase → Providers → Azure, paste the Application (client) ID and the
   secret value. Leave the tenant URL blank for any account type. Then enable
   it.

### Then

Set the providers in the root `config.js`, which is never mirrored from
`public/`:

    oauthProviders: ["google", "apple", "azure"],

Then redeploy, and on the live site sign in once with each provider. The
account should land on the pending screen with the details form. An admin
approves it, and the approval email should arrive.

## Known limits

- **The operator alert for a provider sign-up is queued at once but sent at
  the next sweep.** The sweep runs when an admin opens the admin area,
  approves someone, or a password sign-up happens. This differs from a
  password sign-up, whose `self-signup` call sends the alert immediately. A
  provider sign-in never calls `self-signup`.
- **"Allow new users to sign up" governs provider sign-ups too.** If it is
  off, a new provider account is refused.
- **An existing password account with the same verified address is linked by
  Supabase** (automatic identity linking). It keeps its approval state.
