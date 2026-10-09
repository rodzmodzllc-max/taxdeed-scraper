// supabase/functions/notify-approval/index.ts
//
// Sends the "Your TAXACQ account has been approved" e-mail from the durable
// outbox migration 030 creates (public.account_notifications). Rewritten
// 2026-10-09: the previous version reacted to a database webhook that was
// never configured in production and kept no record of what it sent.
//
// How a notification flows:
//   1. An admin approves (app.js / admin.js: UPDATE profiles SET approved =
//      true). Migration 030's trigger queues ONE account_approved row in the
//      same transaction - no approval, no row; never a second row.
//   2. The admin's browser then calls this function (fire-and-forget). It
//      claims due rows (row-locked, leased), renders the e-mail, sends it
//      through Resend with an idempotency key per row, and records sent /
//      failed (with back-off) / skipped. A failed send never touches the
//      approval itself.
//   3. Retries: any later call processes rows whose back-off has elapsed;
//      the admin panel's "Send pending notifications" button calls it too,
//      and a server-side sweep may call it with the service-role key.
//
// Authorization: the caller's JWT must belong to an administrator, or the
// bearer must be the project's service-role key. The request body is never
// read - no caller can choose a recipient.
//
// Deploy WITH JWT verification (the default). Secrets (shared with the
// project's other functions; never sent to the browser):
//   RESEND_API_KEY        required to send; without it rows fail with NOT_CONFIGURED and retry later
//   SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY  provided by Supabase
// The sender, reply-to, site and mailing address are fixed in
// _shared/approval_notify_core.js (APPROVAL_EMAIL).
import { createClient } from "npm:@supabase/supabase-js@2";
import { authorize, processDue, sendViaResend } from "../_shared/approval_notify_core.js";
import { cors, reply } from "../_shared/billing_http.ts";

const SUPABASE_URL = Deno.env.get("SUPABASE_URL") ?? "";
const SERVICE_ROLE_KEY = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") ?? "";
const RESEND_API_KEY = Deno.env.get("RESEND_API_KEY") ?? "";

const admin = createClient(SUPABASE_URL, SERVICE_ROLE_KEY, { auth: { persistSession: false, autoRefreshToken: false } });

async function isAdminForJwt(jwt: string): Promise<boolean> {
  const { data, error } = await admin.auth.getUser(jwt);
  if (error || !data.user) return false;
  const { data: p } = await admin.from("profiles").select("is_admin").eq("id", data.user.id).maybeSingle();
  return !!(p && p.is_admin === true);
}

Deno.serve(async (req) => {
  const origin = req.headers.get("origin");
  if (req.method === "OPTIONS") return new Response("ok", { headers: cors(origin) });
  if (req.method !== "POST") return reply(405, { error: "method_not_allowed" }, origin);

  const bearer = (req.headers.get("authorization") ?? "").replace(/^Bearer\s+/i, "");
  const auth = await authorize({ bearer, serviceRoleKey: SERVICE_ROLE_KEY, isAdminForJwt });
  if (!auth.ok) return reply(auth.status, { error: auth.reason }, origin);

  const db = {
    async claim(limit: number) {
      const { data, error } = await admin.rpc("claim_account_notifications", { p_limit: limit, p_lease_seconds: 300 });
      if (error) throw new Error(error.code === "PGRST202" ? "outbox_not_installed" : "claim_failed");
      return data ?? [];
    },
    async finish(id: string, attempt: number, outcome: string, messageId: string | null, err: string | null, retry: number) {
      const { data, error } = await admin.rpc("finish_account_notification", {
        p_id: id, p_attempt: attempt, p_outcome: outcome, p_message_id: messageId, p_error: err, p_retry_seconds: retry,
      });
      return !error && data === true;
    },
  };
  try {
    const counts = await processDue({ db, send: (m) => sendViaResend(fetch, RESEND_API_KEY, m), limit: 20 });
    // Counts only - never an address, a body or a provider response.
    console.log(`notify-approval: ${JSON.stringify(counts)}`);
    return reply(200, counts, origin);
  } catch (e) {
    const code = e instanceof Error ? e.message : "error";
    console.error(`notify-approval: ${code}`);
    return reply(code === "outbox_not_installed" ? 503 : 500, { error: code }, origin);
  }
});
