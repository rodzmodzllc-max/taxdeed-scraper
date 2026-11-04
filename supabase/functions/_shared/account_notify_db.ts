// supabase/functions/_shared/account_notify_db.ts
//
// The migration-030 outbox as processDue() (approval_notify_core.js) expects
// it, over a service-role client. Shared by notify-approval (admin / service
// sweeps) and self-signup (sends the new-sign-up alert right after an account
// is created) so there is one outbox and one processor, never two.
import type { SupabaseClient } from "npm:@supabase/supabase-js@2";

export function accountNotifyDb(admin: SupabaseClient) {
  return {
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
}
