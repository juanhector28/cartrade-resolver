"""Self-contained private buyer-request inbox. No third-party dependencies."""
PAGE = r"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow,noarchive">
<title>Solicitudes | CarTrade Operaciones</title>
<style>
:root{color-scheme:light;font-family:Inter,system-ui,-apple-system,sans-serif;color:#203029;background:#f7f9f7}
*{box-sizing:border-box}
body{margin:0}
header{background:#fff;border-bottom:1px solid #e4ebe7;padding:20px max(24px,calc((100vw - 1150px)/2))}
.brand{font-size:23px;font-weight:800;letter-spacing:-1.4px}
.brand span{color:#3d9870}
small{color:#72837a;font-size:12px}
main{max-width:1150px;margin:32px auto;padding:0 22px}
h1{font-size:30px;letter-spacing:-1px;margin:0 0 6px}
.sub{color:#708079;font-size:14px;margin:0 0 28px}
.panel{background:#fff;border:1px solid #e3eae6;border-radius:16px;padding:24px;box-shadow:0 8px 32px rgba(20,39,29,.025)}
#login{max-width:440px;margin:55px auto}
h2{font-size:18px;margin:0 0 16px}
label{font-size:13px;font-weight:600;display:block}
input,select,button{font:inherit}
input[type=password],input[type=email],input[type=text]{display:block;width:100%;padding:12px 14px;border:1px solid #d2dfd7;border-radius:9px;margin:8px 0 16px;font-size:14px}
button{border-radius:9px;padding:10px 15px;background:#277853;border:0;color:#fff;font-size:13px;font-weight:700;cursor:pointer}
button:disabled{opacity:.5;cursor:default}
button.secondary{background:white;color:#315c46;border:1px solid #d5e4d9}
.actions{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:18px;flex-wrap:wrap}
.actions>div{display:flex;gap:8px;align-items:center}
table{width:100%;border-collapse:collapse;font-size:13px}
th{text-align:left;color:#708079;font-size:11px;letter-spacing:.5px;text-transform:uppercase}
td,th{padding:15px 11px;border-bottom:1px solid #edf0ee;vertical-align:top}
.vehicle{font-weight:700;margin-bottom:4px;overflow-wrap:anywhere}
.listing{display:block;color:#31805b;font-size:11px;word-break:break-all;margin-top:4px}
.contact{font-variant-numeric:tabular-nums;font-weight:600}
td select{padding:8px;border:1px solid #d8e4dc;border-radius:8px;background:white;color:#244333;font-size:12px;max-width:145px}
.note{font-size:12px;color:#819086;margin-top:20px}
.error{color:#a83333;min-height:20px;font-size:13px}
.tag{border-radius:40px;background:#eef7f1;color:#23734a;padding:5px 11px;font-size:11px;font-weight:700}
#app[hidden],#login[hidden]{display:none}
#rows-empty{color:#6a8072;padding:32px;text-align:center}
@media(max-width:760px){main{margin-top:18px}h1{font-size:25px}.panel{padding:14px}td,th{padding:10px 7px}table{font-size:11px}.listing{max-width:130px}td select{max-width:105px;font-size:11px}}
</style>
</head>
<body>
<header><div class="brand">cartrade<span>.</span> <small>OPERACIONES</small></div></header>
<main>
<section id="login" class="panel">
  <h1>Acceso privado</h1>
  <p class="sub">Bandeja de solicitudes de compradores</p>
  <form id="login-form">
    <label for="email">Correo de operador autorizado</label>
    <input id="email" type="email" required autocomplete="email" spellcheck="false" maxlength="254">
    <button type="submit">Enviar código de acceso</button>
  </form>
  <form id="verify-form" hidden>
    <p class="sub">Revisa tu correo e introduce el código de acceso.</p>
    <label for="code">Código temporal</label>
    <input id="code" type="text" required inputmode="numeric" pattern="[0-9]{6,12}" autocomplete="one-time-code" minlength="6" maxlength="12">
    <button type="submit">Ingresar a Solicitudes</button>
    <button type="button" class="secondary" id="back">Cambiar correo</button>
  </form>
  <p id="login-error" role="alert" class="error"></p>
  <p class="note">El acceso requiere una cuenta de operador habilitada. La sesión solo permanece en memoria; cerrar la pestaña la finaliza.</p>
</section>
<section id="app" hidden>
  <div class="actions">
    <div>
      <div><h1>Solicitudes</h1><div class="sub">Interés de compra recibido por CarTrade</div></div>
    </div>
    <div><span class="tag">Privado</span><button id="refresh" class="secondary">Actualizar</button><button id="logout" class="secondary">Salir</button></div>
  </div>
  <div class="panel">
    <div style="overflow-x:auto">
      <table aria-label="Solicitudes de compradores">
        <thead><tr><th>Fecha</th><th>Vehículo</th><th>Contacto</th><th>Estado</th></tr></thead>
        <tbody id="rows"></tbody>
      </table>
    </div>
    <p id="rows-empty" hidden>No hay solicitudes registradas.</p>
    <p id="app-error" class="error" role="alert"></p>
    <button id="more" class="secondary" hidden>Cargar más</button>
    <p class="note">Los contactos son privados. No compartir ni exportar sin autorización. Esta bandeja no constituye precalificación bancaria.</p>
  </div>
</section>
</main>
<script>
(function(){
  'use strict';
  var token = '';
  var operatorEmail = '';
  var offset = 0;
  var PAGE_SIZE = 50;
  var statuses = [['received','Nueva'],['in_review','En gestión'],['contacted','Contactado'],['closed','Cerrada']];
  var $ = function(id){return document.getElementById(id);};
  function statusMessage(e){return e && e.message === '401' ? 'Acceso no autorizado. Verifica la clave.' : 'No se pudo completar la operación. Inténtalo de nuevo.';}
  async function api(path, options){
    options = options || {};
    var r = await fetch(path, {
      method: options.method || 'GET',
      credentials: 'omit',
      cache: 'no-store',
      headers: {'Authorization':'Bearer '+token,'Content-Type':'application/json'},
      body: options.body ? JSON.stringify(options.body) : undefined
    });
    if(!r.ok) throw Error(String(r.status));
    return r.json();
  }
  function cell(tr, txt){
    var t = document.createElement('td');
    if(txt !== undefined)t.textContent = String(txt);
    tr.appendChild(t);
    return t;
  }
  function safeLink(url){
    try{var u=new URL(url);return u.protocol==='https:' ? u.href : null;}catch(e){return null;}
  }
  function draw(item){
    var tr = document.createElement('tr');
    var date = new Date(item.created_at);
    cell(tr, Number.isNaN(date.getTime()) ? 'Sin fecha' : date.toLocaleString('es-SV',{dateStyle:'short',timeStyle:'short'}));
    var vehicle = cell(tr);
    var name = document.createElement('div');
    name.className='vehicle';
    name.textContent=String(item.car_name||'Vehículo sin nombre').slice(0,200);
    vehicle.appendChild(name);
    var price = document.createElement('small');
    price.textContent = item.price_usd == null ? 'Precio pendiente' : 'USD '+Number(item.price_usd).toLocaleString('en-US');
    vehicle.appendChild(price);
    var link = safeLink(item.listing_url);
    if(link){
      var a=document.createElement('a');
      a.className='listing';a.textContent='Ver anuncio original ↗';
      a.href=link;a.target='_blank';a.rel='noopener noreferrer';
      vehicle.appendChild(a);
    }
    var contact=cell(tr);
    var phone=String(item.buyer_contact||'').replace(/[^0-9]/g,'');
    var number=document.createElement('div');
    number.textContent=phone;number.className='contact';contact.appendChild(number);
    if(phone.length>=8 && phone.length<=15){
      var wa=document.createElement('a');wa.className='listing';
      wa.href='https://wa.me/'+phone;
      wa.textContent='Abrir WhatsApp ↗';wa.target='_blank';wa.rel='noopener noreferrer';
      contact.appendChild(wa);
    }
    var scell=cell(tr);
    var select=document.createElement('select');
    select.setAttribute('aria-label','Estado de '+name.textContent);
    statuses.forEach(function(entry){
      var o=document.createElement('option');o.value=entry[0];o.textContent=entry[1];
      select.appendChild(o);
    });
    select.value=statuses.some(function(x){return x[0]===item.status;})?item.status:'received';
    select.addEventListener('change',async function(){
      var old=item.status;select.disabled=true;$('app-error').textContent='';
      try{
        await api('/ops/api/solicitudes/'+encodeURIComponent(item.request_id),{method:'PATCH',body:{status:select.value}});
        item.status=select.value;
      }catch(e){
        select.value=old;$('app-error').textContent=statusMessage(e);
      }finally{select.disabled=false;}
    });
    scell.appendChild(select);
    $('rows').appendChild(tr);
  }
  async function load(reset){
    if(reset){offset=0;$('rows').replaceChildren();}
    $('app-error').textContent='';
    $('refresh').disabled=true;
    try{
      var data=await api('/ops/api/solicitudes?offset='+offset+'&limit='+PAGE_SIZE);
      var items=Array.isArray(data.items)?data.items:[];
      items.forEach(draw);
      offset+=items.length;
      $('rows-empty').hidden=offset>0;
      $('more').hidden=items.length<PAGE_SIZE;
    }catch(e){
      $('app-error').textContent=statusMessage(e);
      if(String(e.message)==='401')logout();
      throw e;
    }finally{$('refresh').disabled=false;}
  }
  function logout(){
    token='';operatorEmail='';offset=0;$('rows').replaceChildren();
    $('email').value='';$('code').value='';
    $('verify-form').hidden=true;$('login-form').hidden=false;
    $('app').hidden=true;$('login').hidden=false;
  }
  $('login-form').addEventListener('submit',async function(e){
    e.preventDefault();
    operatorEmail=$('email').value.trim().toLowerCase();
    $('login-error').textContent='';
    try{
      await api('/ops/auth/start',{method:'POST',body:{email:operatorEmail}});
      $('login-form').hidden=true;$('verify-form').hidden=false;
      $('code').focus();
    }catch(error){$('login-error').textContent=statusMessage(error);}
  });
  $('verify-form').addEventListener('submit',async function(e){
    e.preventDefault();$('login-error').textContent='';
    try{
      var session=await api('/ops/auth/verify',{
        method:'POST',body:{email:operatorEmail,code:$('code').value.trim()}
      });
      if(!session.access_token)throw Error('401');
      token=session.access_token;
      await load(true);
      $('code').value='';$('login').hidden=true;$('app').hidden=false;
    }catch(error){
      $('login-error').textContent=statusMessage(error);token='';
    }
  });
  $('back').addEventListener('click',function(){
    operatorEmail='';$('code').value='';$('verify-form').hidden=true;
    $('login-form').hidden=false;$('login-error').textContent='';
  });
  $('logout').addEventListener('click',logout);
  $('refresh').addEventListener('click',function(){load(true).catch(function(){});});
  $('more').addEventListener('click',function(){load(false).catch(function(){});});
})();
</script>
</body></html>"""
