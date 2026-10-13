/* CarTrade: link-first buyer-intent handoff. Never scrapes third-party pages.
 * Requires verified POST /buyer-intents receipt; no false "request sent" UI.
 * Safe to inject into the existing CarTrade hero; feature remains release gated.
 */
(function () {
  "use strict";
  if (window.CT_LINK_FIRST_INSTALLED) return;
  window.CT_LINK_FIRST_INSTALLED = true;
  const host = document.querySelector("#lp9 .search-shell");
  const input = document.getElementById("heroInput");
  if (!host || !input) return;

  function node(tag, txt) {
    const e = document.createElement(tag);
    if (txt !== undefined) e.textContent = txt;
    return e;
  }
  function safeUrl(value) {
    if (value.length > 2048) return null;
    try {
      const p = new URL(value);
      if (p.protocol !== "https:" || p.username || p.password || p.port || !p.hostname
          || !p.hostname.includes(".") || /\s/.test(value)) return null;
      const h = p.hostname.toLowerCase().replace(/\.$/, "");
      if (h === "localhost" || /\.(?:localhost|local|internal)$/.test(h)) return null;
      if (/^\d+(?:\.\d+){3}$/.test(h) || /^\[/.test(p.host)) return null;
      return p.href;
    } catch (_) { return null; }
  }
  const css = node("style");
  css.textContent = [
    "#ct-link-first-entry{margin-top:12px;display:none;align-items:center;gap:11px;flex-wrap:wrap}",
    "#ct-link-first-entry button{border:1px solid #15803d;border-radius:11px;padding:12px 18px;background:#166534;color:#fff;cursor:pointer;font:700 13px system-ui,sans-serif}",
    "#ct-link-first-entry small{font:400 12px system-ui,sans-serif;color:#66736b}",
    "#ct-link-first-dialog{position:fixed;inset:0;z-index:2147482000;display:grid;place-items:center;padding:14px;background:rgba(12,24,15,.65)}",
    "#ct-link-first-dialog .panel{width:min(460px,100%);max-height:96vh;overflow:auto;background:#fff;color:#20332a;border-radius:18px;padding:25px;font:14px system-ui,sans-serif;box-shadow:0 20px 60px #0002}",
    "#ct-link-first-dialog input[type=tel]{display:block;width:100%;border:1px solid #b7cdc0;border-radius:9px;padding:12px;margin:8px 0 16px;box-sizing:border-box;font:16px system-ui,sans-serif}",
    "#ct-link-first-dialog button{font:700 13px system-ui,sans-serif;padding:12px 15px;border-radius:9px;border:1px solid #ddd;cursor:pointer}",
    "#ct-link-first-dialog button.primary{background:#166534;color:white;border-color:#166534}",
    "#ct-link-first-dialog button:disabled{opacity:.55;cursor:not-allowed}"
  ].join("\n");
  document.head.append(css);
  const entry = node("div");
  entry.id = "ct-link-first-entry";
  const start = node("button", "Pedir ayuda con este auto →");
  start.id = "ct-link-first-start";
  start.type = "button";
  entry.append(start, node("small", "Solo necesitamos el enlace. Nosotros nos encargamos del resto."));
  host.append(entry);

  function syncVisibility() {
    const selected = document.querySelector("#lp9 .search-tab.active");
    entry.style.display = selected && selected.dataset.mode === "link" ? "flex" : "none";
  }
  document.querySelectorAll("#lp9 .search-tab").forEach(t =>
    t.addEventListener("click", () => queueMicrotask(syncVisibility))
  );
  syncVisibility();

  let busy = false;
  start.addEventListener("click", () => {
    const link = safeUrl(input.value.trim());
    if (!link) {
      input.setCustomValidity("Pega un enlace HTTPS válido.");
      input.reportValidity();
      input.addEventListener("input", () => input.setCustomValidity(""), {once:true});
      input.focus();
      return;
    }
    const prev = document.getElementById("ct-link-first-dialog");
    prev?.remove();
    const overlay = node("div");
    overlay.id = "ct-link-first-dialog";
    overlay.setAttribute("role", "dialog");
    overlay.setAttribute("aria-modal", "true");
    overlay.setAttribute("aria-label", "Pedir ayuda con este auto");
    const panel = node("div");
    panel.className = "panel";
    const title = node("h2", "Nos encargamos del resto.");
    title.style.margin = "0 0 12px";
    const expl = node("p", "Recibiremos el enlace de este anuncio y podremos ayudarte a revisar el vehículo y sus próximos pasos. Aún no hemos contactado al vendedor ni enviado una solicitud bancaria.");
    expl.style.lineHeight = "1.55";
    const linkLine = node("p", link);
    linkLine.style.cssText = "word-break:break-all;font-size:12px;color:#597064;line-height:1.5";
    const phoneLabel = node("label", "Tu WhatsApp para dar seguimiento");
    phoneLabel.htmlFor = "ct-link-first-phone";
    const phone = node("input");
    phone.id = "ct-link-first-phone";
    phone.type = "tel";
    phone.inputMode = "tel";
    phone.maxLength = 25;
    phone.placeholder = "Ej. +503 7000 0000";
    const consentLabel = node("label");
    consentLabel.style.cssText = "display:flex;gap:10px;line-height:1.5;font-size:13px";
    const checkbox = node("input");
    checkbox.type = "checkbox";
    checkbox.id = "ct-link-first-consent";
    consentLabel.append(checkbox, node("span", "Autorizo a CarTrade a contactarme por WhatsApp sobre este enlace. Entiendo que aún no se ha confirmado disponibilidad ni financiamiento."));
    const errors = node("p");
    errors.id = "ct-link-first-errors";
    errors.setAttribute("role", "alert");
    errors.style.cssText = "font-size:12px;color:#a13232;min-height:15px";
    const submit = node("button", "Enviar mi solicitud");
    submit.className = "primary";
    submit.id = "ct-link-first-submit";
    submit.disabled = true;
    const cancel = node("button", "Cancelar");
    cancel.id = "ct-link-first-cancel";
    cancel.style.marginLeft = "8px";
    checkbox.addEventListener("change", () => { submit.disabled = !checkbox.checked; });
    const requestId = crypto.randomUUID();
    cancel.addEventListener("click", () => { if (!busy) overlay.remove(); });
    submit.addEventListener("click", async () => {
      if (busy || !checkbox.checked) return;
      const normalizedPhone = phone.value.replace(/\D/g, "");
      if (normalizedPhone.length < 8 || normalizedPhone.length > 15) {
        errors.textContent = "Introduce un número de WhatsApp válido.";
        phone.focus();
        return;
      }
      if (safeUrl(input.value.trim()) !== link) {
        errors.textContent = "El enlace cambió. Cierra esta ventana y vuelve a intentarlo.";
        return;
      }
      const api = String(window.CARTRADE_API?.base || "").replace(/\/$/, "");
      if (!api) {
        errors.textContent = "El registro de solicitudes no está disponible por ahora.";
        return;
      }
      busy = true; submit.disabled = true; cancel.disabled = true;
      errors.textContent = "";
      try {
        const response = await fetch(api + "/buyer-intents", {
          method: "POST", credentials: "omit", cache: "no-store",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({
            request_id: requestId, buyer_contact: normalizedPhone,
            contact_channel: "whatsapp", listing_url: link,
            country: "sv", source: "paste_link", consent_to_contact: true
          })
        });
        const receipt = await response.json().catch(() => ({}));
        if (response.status !== 201 || receipt.status !== "received" ||
            receipt.request_id !== requestId) throw Error("not_received");
        window.CT_LINK_FIRST_RECEIPT = {request_id: requestId, status: "received"};
        panel.replaceChildren(node("h2", "Solicitud registrada"), node("p", "CarTrade recibió tu enlace. Te contactaremos por WhatsApp para revisar los siguientes pasos."));
        const done = node("button", "Cerrar");
        done.type = "button";
        done.addEventListener("click", () => overlay.remove());
        panel.append(done);
      } catch (_) {
        errors.textContent = "No se pudo registrar. No se ha enviado tu solicitud; inténtalo más tarde.";
        submit.disabled = false; cancel.disabled = false;
      } finally { busy = false; }
    });
    panel.append(title, expl, linkLine, phoneLabel, phone, consentLabel, errors, submit, cancel);
    overlay.append(panel);
    document.body.append(overlay);
    phone.focus();
  });
})();
