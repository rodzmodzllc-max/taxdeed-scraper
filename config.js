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
  supabasePublishableKey: "sb_publishable_rk5440vza8jwE04v0Rn08w_vltFMEyQ",

  // Optional. Powers the "Satellite" toggle on the Map page (satellite-map.js) -
  // a real satellite/terrain basemap (Mapbox GL JS) as an alternative to the
  // app's own same-origin outline map, which stays the default and needs no
  // key. Leave this blank and the toggle still shows, but switching to
  // Satellite just explains it isn't set up yet - nothing breaks either way.
  //
  // To turn it on:
  //   1. Sign up free at https://www.mapbox.com/ (Mapbox's free tier covers
  //      50,000 map loads/month - see mapbox.com/pricing for current terms).
  //   2. Go to https://account.mapbox.com/access-tokens/ and copy your
  //      "Default public token" (starts with "pk.").
  //   3. Paste it below and redeploy.
  // This token is a PUBLIC token, meant to be shipped in client-side code
  // (same category as the Supabase publishable key above) - Mapbox's own
  // dashboard is where you'd restrict it to this site's URL if you want that.
  mapboxToken: ""
};
