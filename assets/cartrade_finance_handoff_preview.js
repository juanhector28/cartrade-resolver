/* Optional local-only finance handoff, pending a licensed provider integration.
 * No bank call, personal details or persisted application are created here.
 */
(function () {
  'use strict';
  if (window.CT_FINANCE_PREVIEW_INSTALLED) return;
  window.CT_FINANCE_PREVIEW_INSTALLED = true;
  // Observe only the user's successful read-only resolver response.
  var originalFetch = window.fetch;
  window.fetch = function (resource, options) {
    var requestUrl = typeof resource === 'string' ? resource : (resource && resource.url || '');
    var captures = requestUrl.indexOf('/resolve-link') !== -1 && options &&
      String(options.method || 'GET').toUpperCase() === 'POST';
    var sourceUrl = '';
    if (captures) {
      try { sourceUrl = JSON.parse(options.body || '{}').url || ''; } catch (e) {}
    }
    return originalFetch.apply(this, arguments).then(function (response) {
      if (captures && response.ok && sourceUrl) {
        response.clone().json().then(function (data) {
          if (data && data.title && data.price_usd) {
            window.CT_FINANCE_RESOLVED = Object.assign({_source_url: sourceUrl}, data);
          }
        }).catch(function () {});
      }
      return response;
    });
  };

  function node(tag, text, cls) {
    var el = document.createElement(tag);
    if (text != null) el.textContent = text;
    if (cls) el.className = cls;
    return el;
  }
  function getContext() {
    var data = window.CT_FINANCE_RESOLVED || {};
    function value(field) {
      var entry = data[field];
      return entry && typeof entry === 'object' && 'value' in entry ? entry.value : entry;
    }
    var url = String(window.CT_LAST_URL || '').trim();
    if (!url || url !== data._source_url) return null;
    var parsed;
    try { parsed = new URL(url); } catch (e) { return null; }
    if (parsed.protocol !== 'https:' || parsed.username || parsed.password) return null;
    var title = String(value('title') || '').trim().slice(0, 200);
    var price = Number(value('price_usd'));
    var yearValue = value('year');
    var year = yearValue == null ? null : Number(yearValue);
    if (year != null && (!Number.isInteger(year) || year < 1950 || year > 2035)) return null;
    if (!title || !Number.isInteger(price) || price < 500 || price > 200000) return null;
    return {
      schema_version: 1, source_url: parsed.href, title: title,
      price_usd: price, year: year, financing_status: 'not_started'
    };
  }
  function close() {
    var overlay = document.getElementById('ct-finance-overlay');
    if (overlay) overlay.remove();
  }
  function show() {
    close();
    var context = getContext();
    var layer = node('div', null, 'ct-finance-overlay');
    layer.id = 'ct-finance-overlay';
    layer.setAttribute('role', 'dialog');
    layer.setAttribute('aria-modal', 'true');
    layer.setAttribute('aria-label', 'Preparar precalificación');
    var panel = node('div', null, 'ct-finance-panel');
    var heading = node('h2', 'Explorar financiamiento');
    var detail = node('p', 'Revisá los datos del auto antes de avanzar. Esta pantalla todavía no envía solicitudes a bancos.');
    panel.append(heading, detail);
    if (!context) {
      panel.append(node('p', 'Falta confirmar el precio o la fuente del anuncio. No podemos preparar una solicitud con datos incompletos.'));
      var dismiss = node('button', 'Cerrar', 'ct-finance-secondary');
      dismiss.addEventListener('click', close);
      panel.append(dismiss);
      layer.append(panel); document.body.append(layer);
      return;
    }
    var vehicle = node('div', null, 'ct-finance-vehicle');
    vehicle.append(node('strong', context.title));
    vehicle.append(node('p', 'Precio publicado: $' + context.price_usd.toLocaleString('en-US') +
      (context.year ? ' · ' + context.year : '')));
    var link = node('a', 'Ver anuncio original ↗');
    link.href = context.source_url;
    link.target = '_blank'; link.rel = 'noopener noreferrer';
    vehicle.append(link);
    panel.append(vehicle);
    var consentWrap = node('label', null, 'ct-finance-consent');
    var check = document.createElement('input');
    check.type = 'checkbox';
    check.id = 'ct-finance-consent';
    var consentText = node('span', 'Autorizo preparar los datos de este vehículo para explorar opciones de financiamiento. Entiendo que no se ha enviado una solicitud bancaria ni se ha evaluado mi crédito.');
    consentWrap.append(check, consentText);
    panel.append(consentWrap);
    var confirmation = node('button', 'Preparar datos del vehículo', 'ct-finance-primary');
    confirmation.id = 'ct-finance-confirm';
    confirmation.disabled = true;
    check.addEventListener('change', function () { confirmation.disabled = !check.checked; });
    confirmation.addEventListener('click', function () {
      if (!check.checked) return;
      window.CT_FINANCE_CONTEXT = Object.assign({}, context);
      panel.replaceChildren(
        node('h2', 'Datos del vehículo listos'),
        node('p', 'Conservamos el vehículo y su enlace en esta sesión. Ninguna solicitud bancaria ha sido enviada.'),
        node('p', 'La precalificación se habilitará cuando exista un proveedor financiero conectado y autorizado.')
      );
      var done = node('button', 'Entendido', 'ct-finance-primary');
      done.addEventListener('click', close);
      panel.append(done);
    });
    var cancel = node('button', 'Volver', 'ct-finance-secondary');
    cancel.addEventListener('click', close);
    panel.append(confirmation, cancel);
    layer.append(panel);
    layer.addEventListener('click', function (ev) { if (ev.target === layer) close(); });
    document.body.append(layer);
    check.focus();
  }
  function insertEntry() {
    if (document.body.getAttribute('data-ct-screen') !== 'req2') return;
    var stage = document.getElementById('ct-stage');
    if (!stage || stage.querySelector('#ct-finance-start')) return;
    var demo = stage.querySelector('[data-go="req3"]');
    if (!demo || !demo.parentNode) return;
    var button = node('button', 'Explorar financiamiento →', 'ct-finance-entry');
    button.type = 'button';
    button.id = 'ct-finance-start';
    button.addEventListener('click', show);
    demo.parentNode.insertBefore(button, demo);
  }
  var style = node('style');
  style.textContent = [
    '.ct-finance-entry{display:block;margin:8px auto 14px;padding:11px 17px;border:1px solid #bdd9c6;background:#eff8f2;color:#14532d;border-radius:11px;font-weight:700;cursor:pointer}',
    '.ct-finance-overlay{position:fixed;inset:0;z-index:2147483000;background:rgba(22,29,25,.5);display:flex;justify-content:center;align-items:center;padding:18px;font-family:Inter,system-ui,sans-serif}',
    '.ct-finance-panel{width:min(100%,490px);max-height:90vh;overflow-y:auto;background:#fff;color:#18221b;border-radius:20px;padding:28px;box-shadow:0 20px 80px #0002}',
    '.ct-finance-panel h2{margin:0 0 10px;font-size:24px;line-height:1.2;letter-spacing:-.5px}',
    '.ct-finance-panel p{font-size:14px;line-height:1.6;color:#63706a}',
    '.ct-finance-vehicle{border:1px solid #e1e9e4;background:#f7faf8;padding:16px;border-radius:12px;margin:18px 0;overflow-wrap:anywhere}',
    '.ct-finance-vehicle a{color:#18704a;font-size:12px}',
    '.ct-finance-consent{display:flex;align-items:flex-start;gap:10px;font-size:13px;line-height:1.5;margin:15px 0 18px}',
    '.ct-finance-consent input{margin-top:4px;flex-shrink:0}',
    '.ct-finance-primary,.ct-finance-secondary{display:block;width:100%;padding:13px 15px;margin-top:9px;border-radius:10px;font-weight:700;cursor:pointer}',
    '.ct-finance-primary{background:#187349;color:white;border:0}',
    '.ct-finance-primary:disabled{opacity:.45;cursor:not-allowed}',
    '.ct-finance-secondary{background:white;border:1px solid #d6e2d9;color:#334c3e}'
  ].join('');
  document.head.append(style);
  var scheduled = false;
  new MutationObserver(function () {
    if (scheduled) return;
    scheduled = true;
    queueMicrotask(function () { scheduled = false; insertEntry(); });
  }).observe(document.body, { childList: true, subtree: true });
  insertEntry();
})();
