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

Colours follow the TAXACQ brand (forest `#1F3A2E`, ivory `#F8F8F5`, sage `#8CA498`, mist `#D8DED6`, ink `#202925`). Email clients ignore web fonts, so the templates use Arial.

**Reset Password**: subject `Reset your TAXACQ password`, then paste this body:

```html
<div style="background:#F8F8F5;padding:24px 0">
  <div style="font-family:Arial,Helvetica,sans-serif;max-width:560px;margin:0 auto;background:#FFFFFF;border:1px solid #D8DED6;color:#202925">
    <div style="background:#1F3A2E;padding:20px 24px;border-bottom:3px solid #8CA498">
      <div style="color:#F8F8F5;font-size:20px;font-weight:300;letter-spacing:4px">TAXACQ</div>
      <div style="color:#8CA498;font-size:11px;letter-spacing:2px;text-transform:uppercase;margin-top:4px">Tax Acquisition Intelligence</div>
    </div>
    <div style="padding:28px 24px">
      <p style="font-size:15px;line-height:1.5;margin:0 0 20px">We received a request to reset the password for your TAXACQ account.</p>
      <p style="margin:0 0 24px"><a href="https://taxacq.com/index.html?token_hash={{ .TokenHash }}&type=recovery"
         style="display:inline-block;padding:12px 24px;background:#1F3A2E;color:#F8F8F5;text-decoration:none;border-radius:999px;font-size:13px;font-weight:bold;letter-spacing:1px;text-transform:uppercase">Choose a new password</a></p>
      <p style="font-size:13px;line-height:1.5;color:#56695E;margin:0 0 8px">This link works once and expires soon. If you didn't ask for this, ignore this email; nothing on your account changes.</p>
    </div>
    <div style="border-top:1px solid #D8DED6;padding:14px 24px;font-size:12px;color:#56695E">TAXACQ · https://taxacq.com · info@taxacq.com</div>
  </div>
</div>
```

**Confirm signup**: subject `Confirm your TAXACQ email`, body:

```html
<div style="background:#F8F8F5;padding:24px 0">
  <div style="font-family:Arial,Helvetica,sans-serif;max-width:560px;margin:0 auto;background:#FFFFFF;border:1px solid #D8DED6;color:#202925">
    <div style="background:#1F3A2E;padding:20px 24px;border-bottom:3px solid #8CA498">
      <div style="color:#F8F8F5;font-size:20px;font-weight:300;letter-spacing:4px">TAXACQ</div>
      <div style="color:#8CA498;font-size:11px;letter-spacing:2px;text-transform:uppercase;margin-top:4px">Tax Acquisition Intelligence</div>
    </div>
    <div style="padding:28px 24px">
      <p style="font-size:15px;line-height:1.5;margin:0 0 20px">Confirm the email address for your new TAXACQ account.</p>
      <p style="margin:0 0 24px"><a href="https://taxacq.com/index.html?token_hash={{ .TokenHash }}&type=email"
         style="display:inline-block;padding:12px 24px;background:#1F3A2E;color:#F8F8F5;text-decoration:none;border-radius:999px;font-size:13px;font-weight:bold;letter-spacing:1px;text-transform:uppercase">Confirm my email</a></p>
      <p style="font-size:13px;line-height:1.5;color:#56695E;margin:0 0 8px">This link works once and expires soon. If you didn't ask for this, ignore this email; nothing on your account changes.</p>
    </div>
    <div style="border-top:1px solid #D8DED6;padding:14px 24px;font-size:12px;color:#56695E">TAXACQ · https://taxacq.com · info@taxacq.com</div>
  </div>
</div>
```

**Change Email Address**: subject `Confirm your new TAXACQ email`, body:

```html
<div style="background:#F8F8F5;padding:24px 0">
  <div style="font-family:Arial,Helvetica,sans-serif;max-width:560px;margin:0 auto;background:#FFFFFF;border:1px solid #D8DED6;color:#202925">
    <div style="background:#1F3A2E;padding:20px 24px;border-bottom:3px solid #8CA498">
      <div style="color:#F8F8F5;font-size:20px;font-weight:300;letter-spacing:4px">TAXACQ</div>
      <div style="color:#8CA498;font-size:11px;letter-spacing:2px;text-transform:uppercase;margin-top:4px">Tax Acquisition Intelligence</div>
    </div>
    <div style="padding:28px 24px">
      <p style="font-size:15px;line-height:1.5;margin:0 0 20px">Confirm the new email address for your TAXACQ account.</p>
      <p style="margin:0 0 24px"><a href="https://taxacq.com/index.html?token_hash={{ .TokenHash }}&type=email_change"
         style="display:inline-block;padding:12px 24px;background:#1F3A2E;color:#F8F8F5;text-decoration:none;border-radius:999px;font-size:13px;font-weight:bold;letter-spacing:1px;text-transform:uppercase">Confirm new email</a></p>
      <p style="font-size:13px;line-height:1.5;color:#56695E;margin:0 0 8px">This link works once and expires soon. If you didn't ask for this, ignore this email; nothing on your account changes.</p>
    </div>
    <div style="border-top:1px solid #D8DED6;padding:14px 24px;font-size:12px;color:#56695E">TAXACQ · https://taxacq.com · info@taxacq.com</div>
  </div>
</div>
```

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
