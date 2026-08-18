// supabase/functions/notify-approval/index.ts
//
// Fires once per approval: emails the newly-approved user (not the owner)
// letting them know their FL Tax Deed Watchlist account is ready, so they
// don't have to remember to check back and sign in blind. Companion to
// notify-signup, which emails the owner when someone new signs up - this
// one closes the loop back to the user once that sign-up is approved.
//
// Wire-up (see README.md next to this file for the full walkthrough):
//   1. schema-v6-approvals.sql (repo root) must already be applied - this
//      just reacts to public.profiles.approved flipping to true, it
//      doesn't change the gate itself.
//   2. Deploy this function (supabase functions deploy notify-approval).
//   3. Set its secrets (RESEND_API_KEY, NOTIFY_FROM_EMAIL) - same values
//      notify-signup and send-digest already use, if you've set those up.
//   4. Dashboard -> Database -> Webhooks -> Create a new webhook:
//        Table: public.profiles, Event: UPDATE, Type: HTTP Request,
//        URL: this function's URL, Method: POST,
//        Header: X-Notify-Secret: <same value as NOTIFY_WEBHOOK_SECRET>
//
// This is entirely optional - approving someone from the in-app admin
// panel or the Supabase table editor works fine without it. This just
// saves the approved user from having to remember to check back.
//
// Requires these Edge Function secrets:
//   SUPABASE_URL              - auto-provided by Supabase, no action needed
//   SUPABASE_SERVICE_ROLE_KEY - auto-provided by Supabase, no action needed
//   RESEND_API_KEY            - your Resend.com API key (same one
//                                notify-signup / send-digest use, if
//                                you've already set that up)
//   NOTIFY_FROM_EMAIL         - verified "from" address, e.g.
//                                notify@yourdomain.com, or Resend's shared
//                                onboarding@resend.dev while testing
//   NOTIFY_WEBHOOK_SECRET     - optional shared secret; if set, requests must
//                                send header X-Notify-Secret: <value>
//                                (reuse the same value as notify-signup's,
//                                if you already set one there)
//   APP_URL                   - optional; if set, the email links straight
//                                to your app instead of just naming it

import { createClient } from "npm:@supabase/supabase-js@2";

const SUPABASE_URL = Deno.env.get("SUPABASE_URL")!;
const SERVICE_ROLE_KEY = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!;
const RESEND_API_KEY = Deno.env.get("RESEND_API_KEY") ?? "";
const NOTIFY_FROM_EMAIL = Deno.env.get("NOTIFY_FROM_EMAIL") ?? "";
const NOTIFY_WEBHOOK_SECRET = Deno.env.get("NOTIFY_WEBHOOK_SECRET") ?? "";
const APP_URL = Deno.env.get("APP_URL") ?? "";

const admin = createClient(SUPABASE_URL, SERVICE_ROLE_KEY);

function esc(s: unknown): string {
  return String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c] as string)
  );
}

type WebhookPayload = {
  type: string;
  table: string;
  record: { id: string; email: string | null; approved: boolean; approved_at: string | null };
  old_record?: { id: string; email: string | null; approved: boolean } | null;
};

async function sendEmail(to: string, subject: string, html: string): Promise<boolean> {
  if (!RESEND_API_KEY || !NOTIFY_FROM_EMAIL) {
    console.error("RESEND_API_KEY / NOTIFY_FROM_EMAIL not configured - skipping send, dumping to log instead");
    console.log(`Would send to ${to}: ${subject}`);
    return false;
  }
  const resp = await fetch("https://api.resend.com/emails", {
    method: "POST",
    headers: { Authorization: `Bearer ${RESEND_API_KEY}`, "Content-Type": "application/json" },
    body: JSON.stringify({ from: NOTIFY_FROM_EMAIL, to, subject, html }),
  });
  if (!resp.ok) console.error(`Resend send to ${to} failed: ${resp.status} ${await resp.text()}`);
  return resp.ok;
}

Deno.serve(async (req) => {
  if (NOTIFY_WEBHOOK_SECRET) {
    if (req.headers.get("X-Notify-Secret") !== NOTIFY_WEBHOOK_SECRET) {
      return new Response(JSON.stringify({ error: "unauthorized" }), { status: 401 });
    }
  }

  let payload: WebhookPayload;
  try {
    payload = await req.json();
  } catch {
    return new Response(JSON.stringify({ error: "invalid JSON body" }), { status: 400 });
  }
  if (payload.table !== "profiles" || payload.type !== "UPDATE") {
    return new Response(JSON.stringify({ skipped: true, reason: "not a profiles UPDATE" }), {
      headers: { "Content-Type": "application/json" },
    });
  }

  const row = payload.record;
  const was = payload.old_record;
  // Only fire on the false -> true transition, not every profile UPDATE
  // (e.g. an admin toggling is_admin, or re-saving the same row).
  if (!row || !row.approved || (was && was.approved)) {
    return new Response(JSON.stringify({ skipped: true, reason: "not a new approval" }), {
      headers: { "Content-Type": "application/json" },
    });
  }
  if (!row.email) {
    return new Response(JSON.stringify({ skipped: true, reason: "no email on profile" }), {
      headers: { "Content-Type": "application/json" },
    });
  }

  // Sanity-check against the DB rather than trusting the webhook body
  // blindly, same as notify-signup.
  const { data: profile } = await admin.from("profiles").select("approved,email").eq("id", row.id).maybeSingle();
  if (!profile || !profile.approved) {
    return new Response(JSON.stringify({ skipped: true, reason: "not approved in DB" }), {
      headers: { "Content-Type": "application/json" },
    });
  }

  const linkHtml = APP_URL
    ? `<p><a href="${esc(APP_URL)}" style="color:#2563eb">Sign in to the FL Tax Deed Watchlist</a></p>`
    : `<p>Sign in to the FL Tax Deed Watchlist with the email and password you signed up with.</p>`;

  const html = `
    <div style="font-family:system-ui,sans-serif;color:#0f172a">
      <h2 style="margin:0 0 12px">Your account is approved</h2>
      <p>Good news - your FL Tax Deed Watchlist account has been approved. You now have full access to the auction ledgers, filters, and your saved lists.</p>
      ${linkHtml}
    </div>`;

  const ok = await sendEmail(profile.email ?? row.email, "Your FL Tax Deed Watchlist account is approved", html);
  return new Response(JSON.stringify({ sent: ok }), { headers: { "Content-Type": "application/json" } });
});
