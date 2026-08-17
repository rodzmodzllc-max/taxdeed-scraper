// supabase/functions/notify-signup/index.ts
//
// Fires once per new sign-up: emails the account owner (you) that someone
// created an account and is waiting on approval (see
// schema-v6-approvals.sql - new accounts start with profiles.approved =
// false, and every ledger table is walled off from them by RLS until
// that's flipped to true).
//
// Wire-up (see README.md next to this file for the full walkthrough):
//   1. Run schema-v6-approvals.sql in the SQL Editor first, if you haven't.
//   2. Deploy this function (supabase functions deploy notify-signup).
//   3. Set its secrets (RESEND_API_KEY, OWNER_EMAIL, NOTIFY_FROM_EMAIL).
//   4. Dashboard -> Database -> Webhooks -> Create a new webhook:
//        Table: public.profiles, Event: INSERT, Type: HTTP Request,
//        URL: this function's URL, Method: POST,
//        Header: X-Notify-Secret: <same value as NOTIFY_WEBHOOK_SECRET>
//
// This is entirely optional - the approval gate itself (schema-v6 +
// in-app admin panel) works without it. This just saves you from having to
// remember to check the app for new sign-ups.
//
// Requires these Edge Function secrets:
//   SUPABASE_URL              - auto-provided by Supabase, no action needed
//   SUPABASE_SERVICE_ROLE_KEY - auto-provided by Supabase, no action needed
//   RESEND_API_KEY            - your Resend.com API key (same one send-digest
//                                uses, if you've already set that up)
//   OWNER_EMAIL                - where the notification goes (you)
//   NOTIFY_FROM_EMAIL          - verified "from" address, e.g.
//                                notify@yourdomain.com, or Resend's shared
//                                onboarding@resend.dev while testing
//   NOTIFY_WEBHOOK_SECRET      - optional shared secret; if set, requests must
//                                send header X-Notify-Secret: <value>

import { createClient } from "npm:@supabase/supabase-js@2";

const SUPABASE_URL = Deno.env.get("SUPABASE_URL")!;
const SERVICE_ROLE_KEY = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!;
const RESEND_API_KEY = Deno.env.get("RESEND_API_KEY") ?? "";
const OWNER_EMAIL = Deno.env.get("OWNER_EMAIL") ?? "";
const NOTIFY_FROM_EMAIL = Deno.env.get("NOTIFY_FROM_EMAIL") ?? "";
const NOTIFY_WEBHOOK_SECRET = Deno.env.get("NOTIFY_WEBHOOK_SECRET") ?? "";

const admin = createClient(SUPABASE_URL, SERVICE_ROLE_KEY);

function esc(s: unknown): string {
  return String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c] as string)
  );
}

type WebhookPayload = {
  type: string;
  table: string;
  record: { id: string; email: string | null; requested_at: string };
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
  if (!OWNER_EMAIL) {
    return new Response(JSON.stringify({ error: "OWNER_EMAIL secret not set" }), { status: 500 });
  }

  let payload: WebhookPayload;
  try {
    payload = await req.json();
  } catch {
    return new Response(JSON.stringify({ error: "invalid JSON body" }), { status: 400 });
  }
  if (payload.table !== "profiles" || payload.type !== "INSERT") {
    return new Response(JSON.stringify({ skipped: true, reason: "not a profiles INSERT" }), {
      headers: { "Content-Type": "application/json" },
    });
  }

  const newUser = payload.record;
  // Sanity-check against the DB rather than trusting the webhook body
  // blindly - also lets us skip quietly if this row was already approved
  // between the insert and this function running (e.g. the bootstrap row
  // schema-v6-approvals.sql inserts for the owner's own account).
  const { data: profile } = await admin.from("profiles").select("approved").eq("id", newUser.id).maybeSingle();
  if (!profile || profile.approved) {
    return new Response(JSON.stringify({ skipped: true, reason: "already approved or not found" }), {
      headers: { "Content-Type": "application/json" },
    });
  }

  const html = `
    <div style="font-family:system-ui,sans-serif;color:#0f172a">
      <h2 style="margin:0 0 12px">New sign-up awaiting approval</h2>
      <p><b>${esc(newUser.email)}</b> just created an account on the FL Tax Deed Watchlist and is waiting for you to approve access to the ledgers.</p>
      <p style="color:#64748b;font-size:.9em">Sign in to the app and use the "Pending sign-ups" panel at the top to approve or leave it, or run this in the Supabase SQL Editor:</p>
      <pre style="background:#f1f5f9;padding:10px 12px;border-radius:6px;font-size:.85em">update public.profiles set approved = true, approved_at = now() where email = '${esc(newUser.email)}';</pre>
    </div>`;

  const ok = await sendEmail(OWNER_EMAIL, `Approval needed: ${newUser.email}`, html);
  return new Response(JSON.stringify({ sent: ok }), { headers: { "Content-Type": "application/json" } });
});
