// CarTrade Link First. Synthetic-only Supabase staging probe.
// JWT verification is REQUIRED by gateway. No actual buyer contacts can be stored.
const ORIGIN = "https://bright-dragon-cd29a3.netlify.app";
const PROBE_ID = "a4c3a9e4-2d7c-44ab-b53d-9b57409c2026";
const DEMO_URL = "https://example.org/cartrade-demo-vehicle";
const cors = {
  "Access-Control-Allow-Origin": ORIGIN,
  "Access-Control-Allow-Methods": "POST, OPTIONS, GET",
  "Access-Control-Allow-Headers": "authorization, apikey, content-type, x-client-info",
  "Vary": "Origin",
};
function answer(status: number, body: Record<string, unknown>, origin: string | null) {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      "Cache-Control": "no-store, max-age=0",
      "X-Content-Type-Options": "nosniff",
      ...(origin === ORIGIN ? cors : {}),
    },
  });
}
Deno.serve(async (req: Request) => {
  const origin = req.headers.get("origin");
  if (origin !== ORIGIN) {
    return answer(403, { error: "Origen no autorizado" }, origin);
  }
  if (req.method === "OPTIONS") return new Response(null, { status: 204, headers: cors });
  if (req.method === "GET") {
    return answer(200, { service: "cartrade-link-first-staging",
      intake_enabled: false, synthetic_only: true }, origin);
  }
  if (req.method !== "POST") return answer(405, { error: "Método no permitido" }, origin);
  // Strictly limited payload; never ingest contact numbers, personal URLs or
  // arbitrary request IDs. A maximum of one immutable synthetic row exists.
  const length = Number(req.headers.get("content-length") || "0");
  if (length > 350) return answer(413, { error: "Payload demasiado grande" }, origin);
  let data: unknown;
  try {
    const raw = await req.text();
    if (raw.length > 350) throw new Error("oversize");
    data = JSON.parse(raw);
  } catch {
    return answer(400, { error: "JSON inválido" }, origin);
  }
  if (!data || typeof data !== "object" || Array.isArray(data)) {
    return answer(422, { error: "Payload inválido" }, origin);
  }
  const p = data as Record<string, unknown>;
  const names = Object.keys(p).sort().join(",");
  if (names !== "consent_preview,listing_url,mode,probe_id" ||
    p.mode !== "synthetic_demo" ||
    p.probe_id !== PROBE_ID ||
    p.listing_url !== DEMO_URL ||
    p.consent_preview !== true) {
    return answer(422, { error: "Este endpoint solo acepta una prueba sintética" }, origin);
  }
  const supabaseUrl = Deno.env.get("SUPABASE_URL");
  const roleKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY");
  if (!supabaseUrl || !roleKey) {
    return answer(503, { error: "Backend no configurado" }, origin);
  }
  try {
    const response = await fetch(
      supabaseUrl + "/rest/v1/cartrade_link_first_probe?on_conflict=probe_id", {
        method: "POST",
        headers: {
          "apikey": roleKey,
          "authorization": "Bearer " + roleKey,
          "Content-Type": "application/json",
          "Prefer": "resolution=ignore-duplicates,return=minimal",
        },
        body: JSON.stringify({
          probe_id: PROBE_ID,
          listing_url: DEMO_URL,
          buyer_contact: "TEST_ONLY_NO_PHONE",
          is_synthetic: true,
        }),
        signal: AbortSignal.timeout(7000),
      },
    );
    if (!response.ok) {
      return answer(503, { error: "No se pudo registrar la prueba" }, origin);
    }
    return answer(200, {
      status: "synthetic_probe_recorded",
      probe_id: PROBE_ID,
      buyer_data_recorded: false,
      real_intake_enabled: false,
    }, origin);
  } catch {
    return answer(503, { error: "Prueba temporalmente no disponible" }, origin);
  }
});