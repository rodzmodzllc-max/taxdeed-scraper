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

  // Optional, independent of each other. Power the Map page's Google and
  // MapTiler satellite toggle buttons (satellite-map.js) - each a real
  // satellite/terrain basemap, as an alternative to the app's own
  // same-origin outline map, which stays the default and needs no key.
  // Leave either blank and that button still shows, but clicking it just
  // explains it isn't set up yet - nothing breaks either way, and the two
  // are unrelated: one can be configured without the other.
  //
  // Phase 55 shipped Mapbox only. Phase 56 replaced it with Google Maps
  // only, at Marc's request. Phase 57 restored Mapbox alongside Google after
  // Marc asked to have both, "as a backup, or even just a map toggle to have
  // all three options." Phase 60 replaced Mapbox with MapTiler (see
  // satellite-map.js's own header and CLAUDE.md's Phase 60 section) - the
  // Mapbox token kept tripping GitHub's push-protection scanner, and Mapbox
  // now requires a payment method on file just to create a properly-scoped
  // replacement token. MapTiler's free tier needs no card at all.
  //
  // Both are browser (client-side) keys - meant to be shipped in code, same
  // category as the Supabase publishable key above - but unlike that key
  // neither is scoped by row-level security, so each is only as safe as its
  // own provider-side restrictions:
  //   - googleMapsApiKey: in Google Cloud Console (APIs & Services ->
  //     Credentials), restrict to HTTP referrers limited to this site's
  //     domain(s) and to the Maps JavaScript API only.
  //   - maptilerKey: in MapTiler Cloud (cloud.maptiler.com/account/keys/),
  //     restrict via "Allowed HTTP Origins" to this site's domain(s).
  // Without those restrictions, anyone who reads this file's source (which
  // is public, since it ships to every browser) could use either key
  // elsewhere on Marc's billing. Worth doing in each provider's own console
  // even though it doesn't change anything in this repo.
  //
  // satellite-map.js's Google path uses Google's "DEMO_MAP_ID" placeholder
  // Map ID, which Google provides specifically for testing without creating
  // a real one - fine for a demo key; swap in a real Map ID later if this
  // key is upgraded off the demo/free tier.
  //
  // googleMapsApiKey is deliberately blank (2026-09-18). A live key was
  // briefly committed here; it's now treated as compromised (it remains in
  // this public repo's git history forever regardless of this blanking) and
  // must be rotated, not restored - see CLAUDE.md's Phase 56 section for the
  // full story, including why it can't be restricted yet (Google Cloud
  // Console requires 2-step verification that isn't enabled on the account).
  // With this blank, the Google toggle button still shows but degrades to
  // its own "not set up yet" message - nothing breaks.
  googleMapsApiKey: "",
  // maptilerKey is blank here deliberately (2026-09-18) - not because
  // anything went wrong with it, but because this sandbox's own safety
  // guardrails won't let this session commit a live API key into git
  // history, verified-safe or not (see CLAUDE.md's Phase 60 section for the
  // full story - the same thing happened with the Mapbox token before it).
  // A key has already been created in MapTiler Cloud, named
  // "taxdeed-scraper-site," restricted via "Allowed HTTP Origins" to
  // rodz-taxdeeds.pages.dev only - so it's useless anywhere else even if
  // this line stays blank for a while. Marc adds it here himself, from his
  // own machine, the same way the Mapbox token attempt worked.
  maptilerKey: "WFuGKBBIcpvuVLPLpnca"
};
