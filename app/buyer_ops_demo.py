"""Fake-data-only preview of CarTrade buyer operations.

Never imports app.main, Supabase, operator credentials or a real database.
This preview does NOT implement lead intake or server-side status changes.
"""
from __future__ import annotations

from fastapi.responses import HTMLResponse

from .buyer_ops_page import PAGE

DEMO_SCRIPT = r"""<div style="position:fixed;z-index:999;right:12px;top:12px;background:#fff2bb;color:#583d00;border:1px solid #dbb73a;padding:9px 14px;border-radius:10px;font:700 12px system-ui;box-shadow:0 4px 20px #0001" role="status">STAGING · DEMOSTRACIÓN · DATOS FICTICIOS</div>
<script>
(function(){
  'use strict';
  var exampleRows=[
    {request_id:"00000000-0000-4000-8000-000000000001",created_at:"2026-10-12T14:00:00Z",car_name:"Toyota 4Runner TRD 2019 · ejemplo",price_usd:27500,listing_url:"",buyer_contact:"",status:"received"},
    {request_id:"00000000-0000-4000-8000-000000000002",created_at:"2026-10-12T13:30:00Z",car_name:"Kia Sportage 2020 · ejemplo",price_usd:14600,listing_url:"",buyer_contact:"",status:"in_review"},
    {request_id:"00000000-0000-4000-8000-000000000003",created_at:"2026-10-12T12:15:00Z",car_name:"Honda CR-V 2022 · ejemplo",price_usd:23200,listing_url:"",buyer_contact:"",status:"contacted"}
  ];
  var nativeFetch=window.fetch.bind(window);
  window.fetch=function(resource,options){
    var u=typeof resource==="string" ? resource : (resource && resource.url || "");
    if(u.indexOf("/ops/api/solicitudes")===0){
      var response={};
      if(options && options.method==="PATCH"){
        var id=u.split("/").pop();
        var item=exampleRows.find(function(row){return row.request_id===id;});
        var data;try{data=JSON.parse(options.body||"{}");}catch(_){data={};}
        if(item && ["received","in_review","contacted","closed"].indexOf(data.status)!==-1){
          item.status=data.status;
          response={request_id:id,status:data.status};
        }
      }else{
        response={items:exampleRows,offset:0,limit:50};
      }
      return Promise.resolve(new Response(JSON.stringify(response),{
        status:200,headers:{"Content-Type":"application/json","Cache-Control":"no-store"}
      }));
    }
    return nativeFetch(resource,options);
  };
  document.getElementById("login").hidden=true;
  document.getElementById("app").hidden=false;
  var sub=document.querySelector("#app .sub");
  if(sub)sub.textContent="Vista previa sin autenticación. Los contactos están ocultos; los cambios de estado no se guardan.";
  document.getElementById("refresh").click();
})();
</script>"""


def demo_html() -> str:
    page = PAGE.replace(
        "<title>Solicitudes | CarTrade Operaciones</title>",
        "<title>DEMO · Solicitudes | CarTrade Operaciones</title>"
    )
    return page.replace("</body>", DEMO_SCRIPT + "\n</body>")


def demo_response() -> HTMLResponse:
    return HTMLResponse(
        demo_html(),
        headers={
            "Cache-Control": "no-store",
            "X-Robots-Tag": "noindex, nofollow, noarchive",
            "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "no-referrer",
            "Content-Security-Policy": (
                "default-src 'none'; style-src 'unsafe-inline'; "
                "script-src 'unsafe-inline'; connect-src 'self'; "
                "img-src 'none'; form-action 'none'; frame-ancestors 'none'"
            ),
        }
    )
