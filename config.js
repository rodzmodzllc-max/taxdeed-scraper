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
  // a real satellite/terrain basemap (Google Maps JavaScript API) as an
  // alternative to the app's own same-origin outline map, which stays the
  // default and needs no key. Leave this blank and the toggle still shows,
  // but switching to Satellite just explains it isn't set up yet - nothing
  // breaks either way.
  //
  // Phase 56: this replaced an earlier Mapbox-based version of the same
  // toggle (mapboxToken, Phase 55) after Marc got a real Google Maps API key
  // and chose to switch providers outright rather than keep both. The key
  // below is the actual key he supplied for this purpose.
  //
  // This is a browser (client-side) API key - meant to be shipped in code,
  // same category as the Supabase publishable key above - but unlike that
  // key it isn't scoped by row-level security, so it's only as safe as its
  // own restrictions. In Google Cloud Console (APIs & Services ->
  // Credentials), this key should be restricted to: (a) HTTP referrers
  // limited to this site's domain(s), and (b) the Maps JavaScript API only.
  // Without those restrictions, anyone who reads this file's source (which
  // is public, since it ships to every browser) could use the key elsewhere
  // on Marc's Google Cloud billing. Worth doing in Cloud Console even though
  // it doesn't change anything in this repo.
  //
  // satellite-map.js uses Google's "DEMO_MAP_ID" placeholder Map ID, which
  // Google provides specifically for testing without creating a real one -
  // fine for a demo key; swap in a real Map ID later if this key is
  // upgraded off the demo/free tier.
  googleMapsApiKey: ""
};
