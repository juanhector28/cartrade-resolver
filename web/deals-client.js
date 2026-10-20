// CarTrade Deals browser client. No secrets here: publishable Supabase key only.
// Import from a bundler-enabled PWA or a browser module with supabase-js installed.
// This module does not simulate financing, identity checks, or closing.
export class DealsClient {
  constructor({ supabase, apiBase }) {
    if (!supabase?.auth?.getSession) throw new Error("Supabase Auth client required");
    if (!/^https:\/\//.test(apiBase)) throw new Error("Secure API origin required");
    this.supabase = supabase;
    this.apiBase = apiBase.replace(/\/$/, "");
  }
  async _request(path, opts = {}) {
    const { data: { session }, error } = await this.supabase.auth.getSession();
    if (error || !session?.access_token) throw new Error("Iniciá sesión para administrar Deals.");
    const response = await fetch(this.apiBase + "/api/deals" + path, {
      ...opts,
      headers: {
        "Accept": "application/json",
        ...(opts.body ? { "Content-Type": "application/json" } : {}),
        "Authorization": "Bearer " + session.access_token,
      },
      cache: "no-store",
      credentials: "omit",
    });
    if (response.status === 401) throw new Error("Tu sesión expiró. Volvé a iniciar sesión.");
    if (response.status === 404) throw new Error("El Deal no existe o no tenés acceso.");
    if (!response.ok) throw new Error("No se pudo completar la operación (" + response.status + ").");
    return response.json();
  }
  list() { return this._request(""); }
  get(id) {
    if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(id))
      throw new Error("Identificador inválido.");
    return this._request("/" + encodeURIComponent(id));
  }
  create({ market, actor_role, buyer_label, vehicle_title, vehicle_url, asking_price_usd }) {
    if (!["sv", "gt"].includes(market)) throw new Error("Mercado inválido.");
    if (!["buyer", "seller", "broker"].includes(actor_role)) throw new Error("Rol inválido.");
    return this._request("", { method: "POST", body: JSON.stringify({
      market, actor_role, buyer_label, vehicle_title, vehicle_url, asking_price_usd,
    }) });
  }
}
