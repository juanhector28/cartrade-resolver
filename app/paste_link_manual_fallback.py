"""Buyer-safe manual fallback when a vehicle source cannot be read automatically.

Staging-only. All values stay in the browser; no lead, vehicle or scraped
inventory is created. Manually entered fields never become verified facts.
"""
from __future__ import annotations

CSS = """
.manual-helper[hidden]{display:none}
.manual-helper{margin:24px 0 0;background:#fff;border:1px solid #d6e6db;border-radius:18px;padding:24px;box-shadow:0 10px 28px #1a3e2c0a}
.manual-helper h2{font-size:21px;letter-spacing:-.5px;margin:0 0 9px}
.manual-helper p{font-size:13px;color:#657a6d;line-height:1.6;margin:0 0 16px}
.manual-grid{display:grid;grid-template-columns:2fr 1fr 1fr;gap:11px;margin-bottom:12px}
.manual-grid label{font-size:12px;font-weight:650;color:#4c6758}
.manual-grid input{display:block;border:1px solid #d8e3dc;border-radius:8px;width:100%;padding:11px;margin-top:5px;font-size:14px}
.manual-helper .manual-submit{font-size:13px;padding:12px 17px}
.manual-helper .manual-feedback{font-size:12px;color:#9b3e3e;margin-top:8px;min-height:16px}
.manual-kicker{color:#286d4e;font-size:11px;letter-spacing:.3px;font-weight:750;text-transform:uppercase;margin-bottom:10px}
@media(max-width:600px){.manual-helper{padding:18px}.manual-grid{grid-template-columns:1fr}.manual-grid label{width:100%}}
"""

HTML = """
<section id="manual-helper" class="manual-helper" hidden aria-label="Completar vehículo manualmente">
  <div class="manual-kicker">Alternativa a la extracción automática</div>
  <h2>¿No pudimos leer el anuncio?</h2>
  <p>Puedes completar los datos que ves en la publicación original. Son datos proporcionados por ti,
  <strong>no verificados por CarTrade</strong>. No se envían ni guardan y no constituyen una precalificación.</p>
  <form id="manual-form" autocomplete="off">
    <div class="manual-grid">
      <label>Vehículo<input id="manual-title" name="car-title" type="text" required minlength="3" maxlength="150"
        placeholder="Ej. Toyota Corolla 2019"></label>
      <label>Precio publicado (USD)<input id="manual-price" name="car-price" type="number" required min="500"
        max="200000" step="1" placeholder="12500"></label>
      <label>Año (opcional)<input id="manual-year" name="car-year" type="number" min="1950" max="2035"
        step="1" placeholder="2019"></label>
    </div>
    <button class="manual-submit" type="submit">Continuar con estos datos</button>
    <div id="manual-feedback" class="manual-feedback" role="alert"></div>
  </form>
</section>
"""

SCRIPT = r"""
(function(){
  'use strict';
  let attemptedUrl = null;
  const manual = document.getElementById('manual-helper');
  const form = document.getElementById('manual-form');
  const feedback = document.getElementById('manual-feedback');
  const extractLabel = 'Ficha recuperada de la fuente';

  function safeManualLink(raw){
    try{
      const p = new URL(raw);
      if(p.protocol !== 'https:' || !p.hostname || p.username || p.password || p.port) return null;
      return p.href;
    }catch(_){return null;}
  }
  window.CT_manualFallback = {
    show(raw) {
      attemptedUrl = safeManualLink(raw);
      if(!attemptedUrl) return;
      manual.hidden = false;
      feedback.textContent = '';
      document.getElementById('manual-title').focus({preventScroll:true});
    },
    reset() {
      attemptedUrl = null;
      manual.hidden = true;
      feedback.textContent = '';
      document.querySelector('#card .meta').textContent = extractLabel;
    }
  };
  form.addEventListener('submit', function(event){
    event.preventDefault();
    const currentUrl = safeManualLink(document.getElementById('url').value.trim());
    if(!attemptedUrl || !currentUrl || currentUrl !== attemptedUrl){
      feedback.textContent = 'El enlace cambió. Analiza el nuevo enlace antes de continuar.';
      return;
    }
    const title = document.getElementById('manual-title').value.trim();
    const price = Number(document.getElementById('manual-price').value);
    const rawYear = document.getElementById('manual-year').value.trim();
    const year = rawYear ? Number(rawYear) : null;
    if(title.length < 3 || title.length > 150 || !Number.isInteger(price) || price < 500 || price > 200000 ||
       (year !== null && (!Number.isInteger(year) || year < 1950 || year > 2035))){
      feedback.textContent = 'Revisa el nombre, el precio y el año antes de continuar.';
      return;
    }
    document.getElementById('card').style.display = 'block';
    document.querySelector('#card .meta').textContent = 'Datos ingresados por ti · No verificados';
    document.getElementById('title').textContent = title;
    document.getElementById('price').textContent =
      price.toLocaleString('en-US',{style:'currency',currency:'USD',maximumFractionDigits:0});
    document.getElementById('year').textContent = year ? 'Año indicado · '+year : 'Año sin indicar';
    document.getElementById('km').textContent = 'Kilometraje sin verificar';
    const original = document.getElementById('source');
    original.href = attemptedUrl;
    original.textContent = 'Consultar datos en el anuncio original ↗';
    document.getElementById('photo').style.display = 'none';
    document.getElementById('photo').removeAttribute('src');
    document.getElementById('placeholder').style.display = 'block';
    document.getElementById('placeholder').textContent = 'Fotografía no verificada';
    document.getElementById('photo-status').textContent =
      'CarTrade no recuperó ni verificó fotografías de este anuncio.';
    const status = document.getElementById('status');
    status.className = 'status';
    status.textContent = 'Vista manual lista. Precio y vehículo sin verificar.';
    manual.hidden = true;
    document.getElementById('card').scrollIntoView({behavior:'smooth',block:'nearest'});
  });
})();
"""

ERROR_MARKER = '  if(!r.ok)throw new Error(d.detail||"No se pudo recuperar el anuncio");'
START_MARKER = ' e.preventDefault();$("send").disabled=true;$("card").style.display="none";'
FORM_MARKER = '<div id="status" class="status" aria-live="polite"></div>'
STYLE_MARKER = '</style>'
SCRIPT_MARKER = '</script></body></html>'


def attach_manual_fallback(page: str) -> str:
    """Add manual fallback without touching the backend resolver or storage."""
    for marker in (ERROR_MARKER, START_MARKER, FORM_MARKER, STYLE_MARKER, SCRIPT_MARKER):
        if page.count(marker) != 1:
            raise ValueError(f"Expected one marker in staging page: {marker[:40]}")
    if 'id="manual-helper"' in page:
        raise ValueError("Manual helper already present")
    if "</script>" in SCRIPT.lower():
        raise ValueError("Unsafe script terminator")
    page = page.replace(STYLE_MARKER, CSS + STYLE_MARKER)
    page = page.replace(FORM_MARKER, HTML + FORM_MARKER)
    page = page.replace(
        START_MARKER,
        ' e.preventDefault();window.CT_manualFallback.reset();$("send").disabled=true;$("card").style.display="none";',
    )
    page = page.replace(
        ERROR_MARKER,
        '  if(!r.ok){window.CT_manualFallback.show($("url").value.trim()); '
        'let recognized=null;try{const rr=await fetch("/api/reference",'
        '{method:"POST",headers:{"Content-Type":"application/json"},'
        'body:JSON.stringify({url:$("url").value.trim(),country:$("country").value})});'
        'if(rr.ok)recognized=await rr.json()}catch(_){/* offline or blocked */}'
        'if(recognized && recognized.status==="recognized_unstored"){'
        '$("status").className="status";'
        '$("status").textContent="Fuente identificada: "+recognized.source_name+'
        '". Enlace reconocido para pruebas; no se guardó ni se consultó su contenido. "+'
        '"Datos del vehículo pendientes de verificar. Puedes completar los datos abajo.";'
        'return;}'
        'throw new Error(d.detail||"No se pudo recuperar el anuncio");}',
    )
    page = page.replace(SCRIPT_MARKER, SCRIPT + "\n" + SCRIPT_MARKER)
    return page
