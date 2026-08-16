// Fixture config for the CI regression test only - not the real deploy
// config. Values are fake; the test always runs against vendor/supabase-stub.js
// (see tests/vendor/supabase-stub.js), which never makes a real network call,
// so these strings just need to be non-empty to satisfy app.js's startup check.
window.TDW_CONFIG = { supabaseUrl: "https://fake-project.supabase.co", supabasePublishableKey: "sb_publishable_fake" };
