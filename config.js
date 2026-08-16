// Both values are safe to expose publicly. The publishable key only permits
// what the row-level security policies allow, and every table requires a
// signed-in user.
//
// This replaces the old long-lived legacy "anon" JWT with the new
// sb_publishable_... key format - functionally identical from the app's
// point of view (same createClient() call, same RLS enforcement), but
// independently revocable without needing to rotate a shared JWT signing
// secret. Get this value from: Supabase Dashboard -> Project Settings ->
// API Keys -> Publishable key.
//
// IMPORTANT: after you deploy this file, go to Settings -> API Keys ->
// "Legacy anon, service_role API keys" tab and revoke the old legacy anon
// key AND the old legacy service_role key - that's the whole point of this
// migration, closing out the leaked-key rotation from earlier. Don't revoke
// them before deploying, or the live site breaks until the new config.js
// is live.
window.TDW_CONFIG = {
  supabaseUrl: "https://cqnnnvpbocafuvpzfbzu.supabase.co",
  supabasePublishableKey: "sb_publishable_rk5440vza8jwE04v0Rn08w_vltFMEyQ"
};
