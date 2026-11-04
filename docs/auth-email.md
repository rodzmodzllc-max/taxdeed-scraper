# Auth e-mails through Resend, with links to taxacq.com

Added 2026-10-10. Supabase Auth itself sends three kinds of email:

- **Password reset** (`resetPasswordForEmail`).
- **Sign-up confirmation**, only on the fallback `auth.signUp` path.
  `self-signup` sends none.
- **Email-change confirmation.**

By default these leave from Supabase's own sender, `noreply@mail.app.supabase.io`. That sender is capped at a few emails per hour for the whole project, and its links point at `supabase.co`.

Two dashboard changes move these emails onto Resend, from `info@taxacq.com`, with every link pointing at `taxacq.com`. The app side is already in place: `public/app.js` `handleTokenHashLink()`.

## 1. Send through Resend (SMTP)

Supabase → Authentication → Emails → **SMTP Settings** → Enable custom SMTP:

| Field | Value |
|---|---|
| Sender email | `info@taxacq.com` |
| Sender name | `TAXACQ` |
| Host | `smtp.resend.com` |
| Port | `465` |
| Username | `resend` |
| Password | a Resend API key with Sending access. Make a separate key named e.g. `supabase-auth`, so either key can be revoked alone. |

Then go to Authentication → Rate Limits and raise **"Emails sent per hour"**. A custom SMTP sender starts at 30/hour; set what Resend's plan allows.

## 2. Links that point at taxacq.com

Supabase → Authentication → Emails → **Templates**.

**Reset Password**: subject `Reset your TAXACQ password`, then paste this body:

```html
<div style="font-family:Arial,Helvetica,sans-serif;max-width:560px;margin:0 auto;color:#1f2933">
  <div style="background:#0b1a2e;padding:18px 24px;border-bottom:3px solid #c9a24b;color:#fff;font-family:Georgia,serif;font-size:20px;letter-spacing:3px">TAXACQ</div>
  <div style="padding:24px">
    <p style="font-size:15px">We received a request to reset the password for your TAXACQ account.</p>
    <p style="margin:24px 0"><a href="https://taxacq.com/index.html?token_hash={{ .TokenHash }}&type=recovery"
       style="display:inline-block;padding:12px 22px;background:#0b1a2e;color:#fff;text-decoration:none;border-radius:4px;font-weight:bold">Choose a new password</a></p>
    <p style="font-size:13px;color:#5b6675">This link works once and expires soon. If you didn't ask for a reset, ignore this email; your password stays the same.</p>
    <p style="font-size:12px;color:#5b6675">TAXACQ · Tax Acquisition Intelligence · info@taxacq.com</p>
  </div>
</div>
```

**Confirm signup**: subject `Confirm your TAXACQ email`, with the same body and these changes:

- the link is `https://taxacq.com/index.html?token_hash={{ .TokenHash }}&type=email`;
- the button reads "Confirm my email";
- the first line reads "Confirm the email address for your new TAXACQ account."

**Change Email Address**: link `https://taxacq.com/index.html?token_hash={{ .TokenHash }}&type=email_change`.

## How the link works on the site

`handleTokenHashLink()` reads `token_hash` and `type` from the address, removes both from the URL before any request, and calls `sb.auth.verifyOtp({ token_hash, type })`.

- **Valid recovery link.** supabase-js emits `PASSWORD_RECOVERY`, and the existing new-password form opens. The account is still subject to approval: a pending account can reset its password and stays on the pending screen.
- **Used or expired link.** The sign-in screen says so and points to "Forgot password?".

The token is never shown or logged. `tests/recovery_flow_test.mjs` covers both cases with the real supabase-js.

The Redirect URLs allowlist is not involved, because the link no longer goes through Supabase's `/verify` redirect. The older `redirect_to` links keep working too, so changing the template is safe at any time.

## Check after changing it

1. On the sign-in screen, choose "Forgot password?" and enter your own address.
2. The email should come from `TAXACQ <info@taxacq.com>`. It should appear under Resend → Emails, and its button should point at `taxacq.com`.
3. The link should open the new-password form on taxacq.com. Save, then sign in with the new password.
