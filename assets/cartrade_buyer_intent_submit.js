/* Public buyer-request gate. No credit application and no silent lead capture.
 * A receipt is shown only after /buyer-intents explicitly acknowledges storage.
 */
(function () {
  'use strict';
  if (window.CT_BUYER_INTENT_GATE_INSTALLED) return;
  window.CT_BUYER_INTENT_GATE_INSTALLED = true;
  let allowNative = false;
  let active = false;

  const field = (obj, key) => {
    const value = obj && obj[key];
    return value && typeof value === 'object' && 'value' in value ? value.value : value;
  };
  const el = (tag, text) => {
    const n = document.createElement(tag);
    if (text !== undefined) n.textContent = text;
    return n;
  };
  const uuid = () => crypto.randomUUID();
  function close() { document.getElementById('ct-buyer-intent-gate')?.remove(); }
  function displayError(container, message) {
    container.textContent = message;
    container.setAttribute('role', 'alert');
  }

  document.addEventListener('click', function (event) {
    const button = event.target.closest?.('#req-send');
    if (!button || allowNative) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    if (active) return;
    const input = document.getElementById('req-wa-input');
    const phone = String(input?.value || '').replace(/\D/g, '');
    const url = String(window.CT_LAST_URL || '');
    const resolved = window.CT_RESOLVED || window.CT_FINANCE_RESOLVED || {};
    const title = String(field(resolved, 'title') || '').trim();
    let parsed;
    try { parsed = new URL(url); } catch (_) {}
    if (phone.length < 8 || phone.length > 15 || !parsed ||
        parsed.protocol !== 'https:' || !title || title.length > 200) {
      input?.focus();
      return;
    }
    close();
    const overlay = el('div');
    overlay.id = 'ct-buyer-intent-gate';
    Object.assign(overlay.style, {
      position: 'fixed', inset: '0', zIndex: '2147482900',
      background: 'rgba(19,29,22,.58)', display: 'grid',
      placeItems: 'center', padding: '18px'
    });
    overlay.setAttribute('role', 'dialog');
    overlay.setAttribute('aria-modal', 'true');
    overlay.setAttribute('aria-label', 'Confirma tu solicitud');
    const panel = el('div');
    Object.assign(panel.style, {
      maxWidth: '440px', width: '100%', background: '#fff', color: '#233027',
      borderRadius: '16px', padding: '25px', fontFamily: 'system-ui, sans-serif'
    });
    const h = el('h2', 'Confirma tu solicitud');
    h.style.margin = '0 0 10px';
    const summary = el('p', title + ' · Contacto WhatsApp: ' + phone);
    summary.style.cssText = 'font-size:14px;line-height:1.5;overflow-wrap:anywhere';
    const hint = el('p', 'CarTrade registrará tu interés para dar seguimiento. Esto no inicia una solicitud bancaria ni garantiza disponibilidad del auto.');
    hint.style.cssText = 'font-size:13px;line-height:1.6;color:#60716a';
    const label = el('label');
    label.style.cssText = 'display:flex;gap:10px;font-size:13px;line-height:1.45;margin:18px 0';
    const checkbox = el('input');
    checkbox.id = 'ct-buyer-contact-consent';
    checkbox.type = 'checkbox';
    checkbox.style.marginTop = '3px';
    label.append(checkbox, el('span', 'Autorizo a CarTrade a contactarme por WhatsApp acerca de este vehículo. Entiendo que aún no se ha contactado al vendedor.'));
    const requestId = uuid(); // Stable across retries to avoid duplicate buyer requests.
    const submit = el('button', 'Registrar mi solicitud');
    submit.id = 'ct-buyer-intent-submit';
    submit.disabled = true;
    submit.style.cssText = 'width:100%;background:#166a44;color:white;border:0;padding:13px;border-radius:10px;font-weight:700;cursor:pointer';
    const cancel = el('button', 'Cancelar');
    cancel.style.cssText = 'width:100%;background:#fff;color:#324c3d;border:1px solid #c8d9cd;margin-top:8px;padding:11px;border-radius:10px;cursor:pointer';
    const error = el('p');
    error.id = 'ct-buyer-intent-error';
    error.style.cssText = 'color:#b91c1c;font-size:12px;min-height:1em';
    checkbox.addEventListener('change', () => { submit.disabled = !checkbox.checked; });
    cancel.addEventListener('click', close);
    submit.addEventListener('click', async function () {
      if (!checkbox.checked || active) return;
      active = true; submit.disabled = true;
      error.textContent = '';
      const priceRaw = field(resolved, 'price_usd');
      const price = Number(priceRaw);
      const country = window.CT_SEARCH_CONTEXT?.countryCode || 'sv';
      const api = String(window.CARTRADE_API?.base || '').replace(/\/$/, '');
      if (!api) {
        displayError(error, 'No podemos registrar solicitudes en este momento.');
        active = false; submit.disabled = false; return;
      }
      try {
        const response = await fetch(api + '/buyer-intents', {
          method: 'POST', cache: 'no-store', credentials: 'omit',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({
            request_id: requestId, buyer_contact: phone,
            contact_channel: 'whatsapp', listing_url: url, car_name: title,
            price_usd: Number.isInteger(price) && price >= 500 ? price : null,
            country: country, source: 'paste_link', consent_to_contact: true
          })
        });
        const receipt = await response.json().catch(() => ({}));
        if (response.status !== 201 || receipt.status !== 'received' ||
            receipt.request_id !== requestId) throw new Error('not_acknowledged');
        window.CT_BUYER_INTENT_RECEIPT = {status: 'received', request_id: requestId};
        close();
        allowNative = true;
        try { button.click(); } finally { allowNative = false; }
      } catch (_) {
        displayError(error, 'La solicitud NO fue registrada. Intenta de nuevo más tarde.');
      } finally {
        active = false;
        if (submit.isConnected) submit.disabled = !checkbox.checked;
      }
    });
    panel.append(h, summary, hint, label, error, submit, cancel);
    overlay.append(panel);
    document.body.append(overlay);
    checkbox.focus();
  }, true);
})();
