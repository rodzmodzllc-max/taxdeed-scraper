// supabase/functions/_shared/approval_notify_core.js
//
// Account e-mails from the migration-030 outbox - the account-approval e-mail
// (to the approved person) and the operator's new-sign-up alert (to the fixed
// operator address below): content, caller authorization, the Resend call and
// the outbox processor - pure JS with injected I/O so node --test can run it
// (tests/billing/approval_notify.test.mjs) and the Deno handler
// (notify-approval/index.ts) only wires real dependencies.
//
// The recipient is never taken from a request. An approval e-mail goes to the
// address public.claim_account_notifications() returns from profiles for a row
// the approval trigger queued; a sign-up alert goes ONLY to
// SIGNUP_ALERT.to, a constant in this file. Nothing here logs an address, a
// body or a key.

export const APPROVAL_EMAIL = Object.freeze({
  from: "TAXACQ <info@taxacq.com>",
  replyTo: "info@taxacq.com",
  site: "https://taxacq.com",
  contact: "info@taxacq.com",
  address: "6175 NW 167th Ave, Hialeah, FL 33015",
  subject: "Your TAXACQ account has been approved",
});

// Operator alert for every newly created account (kind admin_new_signup).
// The recipient is this constant - not a row value, not a request value.
export const SIGNUP_ALERT = Object.freeze({
  from: "TAXACQ <info@taxacq.com>",
  to: "info@taxacq.com",
  // admin.html's "Pending sign-ups" card (section id "pending") - the page
  // where an administrator approves or leaves an account pending.
  adminUrl: "https://taxacq.com/admin.html#pending",
  subject: "New TAXACQ account created",
});

export const MAX_ATTEMPTS = 8;

export function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

const EMAIL_RE = /^[^\s@<>"',;:()\[\]\\]+@[^\s@<>"',;:()\[\]\\]+\.[A-Za-z]{2,}$/;
export function validEmail(s) {
  return typeof s === "string" && s.length <= 254 && EMAIL_RE.test(s.trim());
}

// Back-off after attempt n (1-based): 5 min, 15 min, 1 h, 3 h, 6 h, then 12 h.
export function retrySeconds(attempt) {
  return [300, 900, 3600, 10800, 21600][Math.max(0, attempt - 1)] ?? 43200;
}

const LEDGERS = [
  ["Auctions", "research scheduled tax-sale opportunities and available auction information."],
  ["Available", "explore government-held and post-sale inventory with documented purchase or application paths where available."],
  ["Liens & Certificates", "research tax liens and certificates separately from ownership of the underlying property."],
];

// Account approval only - never a statement about a subscription or paid access.
export function renderApprovalEmail(cfg = APPROVAL_EMAIL) {
  const site = /^https:\/\/[a-z0-9.-]+(\/[^\s"'<>]*)?$/i.test(cfg.site) ? cfg.site : APPROVAL_EMAIL.site;
  const text = [
    "Welcome to TAXACQ.",
    "",
    "Your account has been approved, and you can now sign in to Tax Acquisition Intelligence.",
    "",
    "TAXACQ helps you research tax-sale opportunities through three dedicated ledgers:",
    "",
    ...LEDGERS.map(([n, d]) => `- ${n} - ${d}`),
    "",
    "Start exploring properties, review source records, examine parcel information, and organize your due diligence.",
    "",
    `Access TAXACQ: ${site}`,
    "",
    "Coverage, source freshness, and available purchase information vary by state and source.",
    "",
    "If you have trouble accessing your account, reply to this email and we will help.",
    "",
    "TAXACQ",
    "Tax Acquisition Intelligence",
    "Find the property. Understand the record. Know how to acquire it.",
    "",
    cfg.contact,
    cfg.address,
  ].join("\n");

  const navy = "#0b1a2e", gold = "#c9a24b", ink = "#1f2933", muted = "#5b6675", paper = "#f4f1ea";
  const li = LEDGERS.map(([n, d]) =>
    `<tr><td style="padding:6px 0;font-size:15px;line-height:1.5;color:${ink}"><strong style="color:${navy}">${esc(n)}</strong> &mdash; ${esc(d)}</td></tr>`).join("");
  const html = `<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>${esc(cfg.subject)}</title></head>
<body style="margin:0;padding:0;background:${paper}">
<div style="display:none;max-height:0;overflow:hidden">Your account has been approved. You can now sign in to TAXACQ.</div>
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:${paper}"><tr><td align="center" style="padding:28px 12px">
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="max-width:600px;background:#ffffff;border-radius:6px;overflow:hidden;font-family:Georgia,'Times New Roman',serif">
<tr><td style="background:${navy};padding:26px 32px;border-bottom:3px solid ${gold}">
  <div style="font-size:24px;letter-spacing:4px;color:#ffffff;font-weight:bold">TAXACQ</div>
  <div style="font-family:Arial,Helvetica,sans-serif;font-size:12px;letter-spacing:2px;color:${gold};text-transform:uppercase;margin-top:4px">Tax Acquisition Intelligence</div>
</td></tr>
<tr><td style="padding:32px 32px 8px;font-family:Arial,Helvetica,sans-serif">
  <h1 style="margin:0 0 14px;font-family:Georgia,'Times New Roman',serif;font-size:24px;font-weight:normal;color:${navy}">Welcome to TAXACQ.</h1>
  <p style="margin:0 0 16px;font-size:15px;line-height:1.6;color:${ink}">Your account has been approved, and you can now sign in to Tax Acquisition Intelligence.</p>
  <p style="margin:0 0 8px;font-size:15px;line-height:1.6;color:${ink}">TAXACQ helps you research tax-sale opportunities through three dedicated ledgers:</p>
  <table role="presentation" cellspacing="0" cellpadding="0" style="margin:0 0 16px">${li}</table>
  <p style="margin:0 0 24px;font-size:15px;line-height:1.6;color:${ink}">Start exploring properties, review source records, examine parcel information, and organize your due diligence.</p>
  <table role="presentation" cellspacing="0" cellpadding="0" style="margin:0 0 26px"><tr><td style="background:${navy};border-radius:4px;border:1px solid ${gold}">
    <a href="${esc(site)}" style="display:inline-block;padding:13px 28px;font-size:15px;font-weight:bold;color:#ffffff;text-decoration:none;letter-spacing:1px">Access TAXACQ</a>
  </td></tr></table>
  <p style="margin:0 0 12px;font-size:13px;line-height:1.6;color:${muted}">Coverage, source freshness, and available purchase information vary by state and source.</p>
  <p style="margin:0 0 24px;font-size:13px;line-height:1.6;color:${muted}">If you have trouble accessing your account, reply to this email and we will help.</p>
</td></tr>
<tr><td style="padding:20px 32px 28px;border-top:1px solid #e5e0d4;font-family:Arial,Helvetica,sans-serif;font-size:12px;line-height:1.6;color:${muted}">
  <div style="color:${navy};font-weight:bold;letter-spacing:2px">TAXACQ</div>
  <div>Tax Acquisition Intelligence</div>
  <div style="color:${gold};font-style:italic">Find the property. Understand the record. Know how to acquire it.</div>
  <div style="margin-top:8px"><a href="mailto:${esc(cfg.contact)}" style="color:${muted}">${esc(cfg.contact)}</a> &middot; <a href="${esc(site)}" style="color:${muted}">taxacq.com</a></div>
  <div>${esc(cfg.address)}</div>
</td></tr>
</table></td></tr></table>
</body></html>`;
  return { subject: cfg.subject, html, text };
}

// "2026-10-09 14:32 UTC" - deterministic, no locale.
export function utcStamp(value) {
  const d = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(d.getTime())) return "Not recorded";
  return d.toISOString().slice(0, 16).replace("T", " ") + " UTC";
}

// The operator alert. Statuses are the ones read at send time from the
// account itself (auth.users / profiles), never assumed. The account e-mail
// is user-supplied text: it is only ever escaped, and an implausible one is
// shown as such rather than dropped.
export function renderSignupAlert(row, cfg = SIGNUP_ALERT) {
  const adminUrl = /^https:\/\/[a-z0-9.-]+\/[^\s"'<>]*$/i.test(cfg.adminUrl) ? cfg.adminUrl : SIGNUP_ALERT.adminUrl;
  const email = typeof row.email === "string" && row.email.trim() ? row.email.trim().slice(0, 254) : "Not recorded";
  const facts = [
    ["Signed up", utcStamp(row.signed_up_at)],
    ["Account email", email + (email !== "Not recorded" && !validEmail(email) ? " (not a valid address)" : "")],
    ["Email confirmation", row.email_confirmed === true ? "Confirmed" : "Not confirmed"],
    ["Approval", row.approved === true ? "Approved" : "Pending approval"],
  ];
  const text = [
    "A new TAXACQ account was created.",
    "",
    ...facts.map(([k, v]) => `${k}: ${v}`),
    "",
    "Statuses are as of when this alert was sent.",
    "",
    `Review pending sign-ups: ${adminUrl}`,
    "",
    "Automatic operator alert. The account holder does not receive this message.",
  ].join("\n");
  const rows = facts.map(([k, v]) =>
    `<tr><td style="padding:4px 12px 4px 0;color:#5b6675;font-size:14px">${esc(k)}</td><td style="padding:4px 0;color:#1f2933;font-size:14px"><strong>${esc(v)}</strong></td></tr>`).join("");
  const html = `<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>${esc(cfg.subject)}</title></head>
<body style="margin:0;padding:24px 12px;background:#f4f1ea;font-family:Arial,Helvetica,sans-serif">
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="max-width:560px;margin:0 auto;background:#ffffff;border-radius:6px">
<tr><td style="background:#0b1a2e;padding:16px 24px;border-bottom:3px solid #c9a24b;color:#ffffff;font-family:Georgia,'Times New Roman',serif;font-size:18px;letter-spacing:3px">TAXACQ &middot; Operator alert</td></tr>
<tr><td style="padding:20px 24px">
  <p style="margin:0 0 12px;font-size:15px;color:#0b1a2e">A new TAXACQ account was created.</p>
  <table role="presentation" cellspacing="0" cellpadding="0">${rows}</table>
  <p style="margin:12px 0 18px;font-size:12px;color:#5b6675">Statuses are as of when this alert was sent.</p>
  <a href="${esc(adminUrl)}" style="display:inline-block;padding:10px 18px;background:#0b1a2e;color:#ffffff;text-decoration:none;border-radius:4px;font-size:14px">Review pending sign-ups</a>
  <p style="margin:18px 0 0;font-size:12px;color:#5b6675">Automatic operator alert. The account holder does not receive this message.</p>
</td></tr></table></body></html>`;
  return { subject: cfg.subject, html, text };
}

// Who may run the processor: an administrator (JWT checked against
// profiles.is_admin by the caller-supplied lookup) or the server itself
// (the project's service-role key as the bearer - e.g. a scheduled sweep).
// Everyone else is refused; nothing in the request names a recipient.
export async function authorize({ bearer, serviceRoleKey, isAdminForJwt }) {
  if (!bearer) return { ok: false, status: 401, reason: "not_signed_in" };
  if (serviceRoleKey && bearer === serviceRoleKey) return { ok: true, as: "service" };
  let admin = false;
  try { admin = await isAdminForJwt(bearer); } catch { admin = false; }
  return admin ? { ok: true, as: "admin" } : { ok: false, status: 403, reason: "admin_only" };
}

// One Resend call. Returns { ok, id } or { ok:false, code } - a code, never
// the provider's response body (it can echo the address).
export async function sendViaResend(fetchFn, apiKey, msg) {
  if (!apiKey) return { ok: false, code: "NOT_CONFIGURED" };
  let resp;
  try {
    resp = await fetchFn("https://api.resend.com/emails", {
      method: "POST",
      headers: { Authorization: `Bearer ${apiKey}`, "Content-Type": "application/json", "Idempotency-Key": msg.idempotencyKey },
      body: JSON.stringify({ from: msg.from, to: [msg.to], reply_to: msg.replyTo, subject: msg.subject, html: msg.html, text: msg.text }),
    });
  } catch {
    return { ok: false, code: "NETWORK" };
  }
  if (!resp.ok) return { ok: false, code: `HTTP_${resp.status}` };
  let id = null;
  try { id = (await resp.json()).id ?? null; } catch { id = null; }
  return { ok: true, id };
}

// Process due notifications: claim (row-locked, leased), send, record.
// db: { claim(limit) -> [{id, kind, attempt, email, approved, signed_up_at, email_confirmed}],
//       finish(id, attempt, outcome, messageId, error, retrySeconds) -> bool }
// send(msg) -> { ok, id } | { ok:false, code }
// Returns counts only.
export async function processDue({ db, send, limit = 10, cfg = APPROVAL_EMAIL, alert = SIGNUP_ALERT }) {
  const counts = { claimed: 0, sent: 0, failed: 0, skipped: 0, stale: 0 };
  const rows = (await db.claim(limit)) || [];
  counts.claimed = rows.length;
  const mail = renderApprovalEmail(cfg);
  for (const r of rows) {
    let outcome, messageId = null, error = null;
    if (r.kind === "admin_new_signup") {
      // Sent whatever the account's statuses are - the alert reports them.
      const a = renderSignupAlert(r, alert);
      const res = await send({ from: alert.from, replyTo: alert.to, to: alert.to, subject: a.subject, html: a.html,
                               text: a.text, idempotencyKey: `admin_new_signup/${r.id}` });
      if (res && res.ok) { outcome = "sent"; messageId = res.id || null; }
      else { outcome = "failed"; error = (res && res.code) || "UNKNOWN"; }
    }
    else if (r.kind !== "account_approved") { outcome = "skipped"; error = "UNKNOWN_KIND"; }
    else if (r.approved !== true) { outcome = "skipped"; error = "NOT_APPROVED"; }
    else if (!validEmail(r.email)) { outcome = "skipped"; error = "NO_VALID_EMAIL"; }
    else {
      const res = await send({ from: cfg.from, replyTo: cfg.replyTo, to: r.email.trim(), subject: mail.subject, html: mail.html,
                               text: mail.text, idempotencyKey: `account_approved/${r.id}` });
      if (res && res.ok) { outcome = "sent"; messageId = res.id || null; }
      else { outcome = "failed"; error = (res && res.code) || "UNKNOWN"; }
    }
    const recorded = await db.finish(r.id, r.attempt, outcome, messageId, error, retrySeconds(r.attempt));
    if (!recorded) counts.stale += 1;
    counts[outcome] += 1;
  }
  return counts;
}
