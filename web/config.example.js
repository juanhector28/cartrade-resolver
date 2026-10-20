// Copy to config.js in a staging deployment. These are public values only.
// Do not place Supabase service_role keys, secrets, or bank credentials here.
export const config = Object.freeze({
  supabaseUrl: "https://YOUR_PROJECT.supabase.co",
  supabasePublishableKey: "YOUR_PUBLIC_ANON_OR_PUBLISHABLE_KEY",
  apiBase: "https://resolver.cartrade.live"
});
