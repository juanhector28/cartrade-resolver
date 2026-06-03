/* CarTrade — frontend wiring to the resolver (replaces the embedded CT_CARS engine).
   Point RESOLVER_BASE at your Render URL. Drop this in AFTER the hero markup.
   It reuses the existing hero DOM: #clzcInp #clzcSeeds #clQuery #clCards #clStatus #heroLinkInput */
(function () {
  var RESOLVER_BASE = "https://cartrade-resolver.onrender.com/"; // <-- set me
  var COUNTRY = "sv"; // default market; set per visitor if you geo-detect

  var SEEDS = [
    ["Para mi familia", "SUV para mi familia"],
    ["Primer auto", "Mi primer auto, algo económico"],
    ["Trabajo / pickup", "Una pickup para trabajo"],
    ["Menos de $10k", "Algo bueno menos de $10k"],
    ["El más full", "Lo más full que tengan"],
  ];

  function money(n) { return "$" + (n || 0).toLocaleString("en-US"); }
  function el(id) { return document.getElementById(id); }

  function cardHTML(c, i) {
    var tagClass = i === 0 ? "cl-tag-1" : "cl-tag-2";
    var specs = [c.year, c.km ? c.km.toLocaleString("en-US") + " km" : null, c.transmission]
      .filter(Boolean).join(" · ");
    var mes = c.monthly_est ? money(c.monthly_est) + "/mes" : "Consultar";
    return '<a class="cl-card" href="' + (c.url || "#") + '" target="_blank" rel="noopener">' +
      '<img class="th" src="' + (c.primary_photo || "") + '" onerror="this.style.opacity=0"/>' +
      '<div class="info"><span class="cl-tag ' + tagClass + '">' + (c.tag || "Opción") + '</span>' +
      '<div class="cl-name">' + ((c.make || "") + " " + (c.model || "")).trim() + '</div>' +
      '<div class="cl-specs">' + specs + '</div>' +
      '<div class="cl-money"><span class="cl-mes">' + mes + '</span>' +
      '<span class="cl-total">' + money(c.price_usd) + ' total</span></div>' +
      '</div></a>';
  }

  function paint(query, results) {
    if (el("clQuery")) el("clQuery").textContent = "\u201c" + query + "\u201d";
    var C = el("clCards");
    if (!C) return;
    C.style.opacity = 0;
    setTimeout(function () {
      C.innerHTML = results.length
        ? results.map(cardHTML).join("")
        : '<div style="opacity:.6;font-size:13px;padding:8px">Sin coincidencias. Probá ampliar el presupuesto.</div>';
      C.style.opacity = 1;
    }, 200);
  }

  function search(q) {
    var s = el("clStatus"); if (s) s.innerHTML = "<i></i>buscando...";
    fetch(RESOLVER_BASE + "/carly/search", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ q: q, country: COUNTRY, limit: 3 }),
    })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (s) s.innerHTML = "<i></i>resultados para vos";
        paint(q, data.results || []);
      })
      .catch(function () {
        if (s) s.innerHTML = "<i></i>error de conexión";
        paint(q, []);
      });
  }

  window.CTCarly = {
    seed: function (sd) { search(sd); },
    send: function () { var i = el("clzcInp"); if (i && i.value.trim()) search(i.value.trim()); },
  };

  window.handleHeroLink = function () {
    var i = el("heroLinkInput");
    if (!i || !i.value.trim()) return;
    fetch(RESOLVER_BASE + "/resolve", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url: i.value.trim() }),
    })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        // data.found -> open close flow with data.listing ; else -> lead capture
        alert(data.message); // replace with your real UI / flow
      })
      .catch(function () { alert("No pudimos resolver el enlace. Intentá de nuevo."); });
  };

  function init() {
    var c = el("clzcSeeds");
    if (c) {
      c.innerHTML = "";
      SEEDS.forEach(function (sd) {
        var b = document.createElement("button");
        b.textContent = sd[0];
        b.onclick = function () { CTCarly.seed(sd[1]); };
        c.appendChild(b);
      });
    }
    var i = el("clzcInp");
    if (i) i.addEventListener("keydown", function (e) { if (e.key === "Enter") CTCarly.send(); });
  }
  if (document.readyState !== "loading") init();
  else document.addEventListener("DOMContentLoaded", init);
})();
