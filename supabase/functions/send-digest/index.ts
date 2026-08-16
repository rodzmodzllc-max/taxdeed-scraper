// supabase/functions/send-digest/index.ts
//
// Scheduled job: emails each user a summary of their FAVORITED auctions
// whose sale_date falls in the next DIGEST_DAYS days. Intended to be called
// on a daily cron (see ../../schema-v5-digest.sql and the setup README next
// to this file for how to wire that up) - it does nothing destructive and
// is safe to invoke more than once a day (idempotent: it always just
// reflects current favorites/sale_dates, no "already sent" state is kept).
//
// Requires these Edge Function secrets (see README.md for how to set them):
//   SUPABASE_URL               - auto-provided by Supabase, no action needed
//   SUPABASE_SERVICE_ROLE_KEY  - auto-provided by Supabase, no action needed
//   RESEND_API_KEY             - your Resend.com API key (or swap sendEmail()
//                                 below for whatever email API you use)
//   DIGEST_FROM_EMAIL          - verified "from" address, e.g. digest@yourdomain.com
//   DIGEST_DAYS                - optional, defaults to 7
//   DIGEST_CRON_SECRET         - optional shared secret; if set, requests must
//                                 send header  X-Digest-Secret: <value>

import { createClient } from "npm:@supabase/supabase-js@2";

const SUPABASE_URL = Deno.env.get("SUPABASE_URL")!;
const SERVICE_ROLE_KEY = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!;
const RESEND_API_KEY = Deno.env.get("RESEND_API_KEY") ?? "";
const DIGEST_FROM_EMAIL = Deno.env.get("DIGEST_FROM_EMAIL") ?? "";
const DIGEST_DAYS = Number(Deno.env.get("DIGEST_DAYS") ?? "7");
const DIGEST_CRON_SECRET = Deno.env.get("DIGEST_CRON_SECRET") ?? "";

const admin = createClient(SUPABASE_URL, SERVICE_ROLE_KEY);

function esc(s: unknown): string {
  return String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c] as string)
  );
}

function fmtDate(d: string): string {
  return new Date(d + "T00:00:00Z").toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    timeZone: "UTC",
  });
}

function fmtMoney(n: number | null): string {
  return n == null ? "-" : `$${Number(n).toLocaleString()}`;
}

type Row = {
  user_id: string;
  property_id: string;
  county: string;
  address: string;
  case_no: string;
  bid: number;
  market: number | null;
  sale_date: string;
  url_auction: string | null;
  days_out: number;
};

function buildEmailHtml(rows: Row[]): string {
  const rowsHtml = rows
    .map(
      (p) => `
    <tr>
      <td style="padding:6px 10px;border-bottom:1px solid #e2e8f0">${esc(p.county)}</td>
      <td style="padding:6px 10px;border-bottom:1px solid #e2e8f0">${esc(p.address)}</td>
      <td style="padding:6px 10px;border-bottom:1px solid #e2e8f0">${fmtDate(p.sale_date)} (${p.days_out}d)</td>
      <td style="padding:6px 10px;border-bottom:1px solid #e2e8f0">${fmtMoney(p.bid)}</td>
      <td style="padding:6px 10px;border-bottom:1px solid #e2e8f0">${
        p.url_auction ? `<a href="${esc(p.url_auction)}">Auction listing</a>` : ""
      }</td>
    </tr>`
    )
    .join("");

  return `
    <div style="font-family:system-ui,sans-serif;color:#0f172a">
      <h2 style="margin:0 0 12px">${rows.length} favorited auction${rows.length === 1 ? "" : "s"} closing in the next ${DIGEST_DAYS} days</h2>
      <table style="border-collapse:collapse;width:100%">
        <tr style="text-align:left;background:#f1f5f9">
          <th style="padding:6px 10px">County</th>
          <th style="padding:6px 10px">Address</th>
          <th style="padding:6px 10px">Sale date</th>
          <th style="padding:6px 10px">Opening bid</th>
          <th style="padding:6px 10px">Link</th>
        </tr>
        ${rowsHtml}
      </table>
      <p style="color:#64748b;font-size:.9em;margin-top:16px">
        You're getting this because these properties are in your favorites on the FL Tax Deed Watchlist.
        Best-effort public records search - not a certified title search.
      </p>
    </div>`;
}

async function sendEmail(to: string, html: string, count: number): Promise<boolean> {
  if (!RESEND_API_KEY || !DIGEST_FROM_EMAIL) {
    console.error("RESEND_API_KEY / DIGEST_FROM_EMAIL not configured - skipping send, dumping to log instead");
    console.log(`Would send to ${to}: ${count} closing-soon favorite(s)`);
    return false;
  }
  // Swap this block for your provider of choice (SendGrid, Postmark, SES,
  // Gmail API via a service account, etc.) if you're not using Resend -
  // everything above this point (the query + HTML build) stays the same.
  const resp = await fetch("https://api.resend.com/emails", {
    method: "POST",
    headers: {
      Authorization: `Bearer ${RESEND_API_KEY}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      from: DIGEST_FROM_EMAIL,
      to,
      subject: `${count} tax deed auction${count === 1 ? "" : "s"} closing soon`,
      html,
    }),
  });
  if (!resp.ok) {
    console.error(`Resend send to ${to} failed: ${resp.status} ${await resp.text()}`);
  }
  return resp.ok;
}

Deno.serve(async (req) => {
  if (DIGEST_CRON_SECRET) {
    if (req.headers.get("X-Digest-Secret") !== DIGEST_CRON_SECRET) {
      return new Response(JSON.stringify({ error: "unauthorized" }), { status: 401 });
    }
  }

  const { data: rows, error } = await admin.rpc("digest_candidates", { days_ahead: DIGEST_DAYS });
  if (error) {
    console.error("digest_candidates RPC failed:", error.message);
    return new Response(JSON.stringify({ error: error.message }), { status: 500 });
  }
  if (!rows || rows.length === 0) {
    return new Response(JSON.stringify({ sent: 0, users: 0, reason: "no candidates" }), {
      headers: { "Content-Type": "application/json" },
    });
  }

  const byUser = new Map<string, Row[]>();
  for (const r of rows as Row[]) {
    if (!byUser.has(r.user_id)) byUser.set(r.user_id, []);
    byUser.get(r.user_id)!.push(r);
  }

  let sent = 0;
  const failures: string[] = [];
  for (const [userId, props] of byUser) {
    const { data: userResp, error: userErr } = await admin.auth.admin.getUserById(userId);
    const email = userResp?.user?.email;
    if (userErr || !email) {
      failures.push(`${userId}: could not resolve email (${userErr?.message ?? "no email on account"})`);
      continue;
    }
    const html = buildEmailHtml(props);
    const ok = await sendEmail(email, html, props.length);
    if (ok) sent++;
    else failures.push(`${userId} <${email}>: send failed`);
  }

  return new Response(JSON.stringify({ sent, users: byUser.size, failures }), {
    headers: { "Content-Type": "application/json" },
  });
});
