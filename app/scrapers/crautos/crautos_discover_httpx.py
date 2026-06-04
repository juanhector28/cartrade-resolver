"""
crautos_discover_httpx.py
Descubrimiento de listings de crautos.com SIN navegador.

Hallazgo clave (de tus pruebas):
  El parámetro ?c=NNNNN NO es un número de página adivinable. Es un token de
  cursor que el servidor rota dentro de TU sesión (lo viste ir 32->31->32->33->34).
  Por eso no se puede saltar ni reconstruir desde afuera.

La solución: no adivinamos el c, lo LEEMOS. Cada página de resultados trae el
enlace de "siguiente" (el ícono .fa-angle-right) con el c correcto ya puesto.
Manteniendo la cookie de sesión, seguimos ese enlace de página en página.

Requiere:  pip install httpx selectolax
"""

import asyncio
import re
from urllib.parse import urljoin
import httpx
from selectolax.parser import HTMLParser

BASE = "https://crautos.com/autosusados/"
START = urljoin(BASE, "searchresults.cfm")   # buscar sin filtros = inventario completo
ID_RE = re.compile(r"cardetail\.cfm\?c=(\d+)")

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/124.0 Safari/537.36"),
    "Referer": BASE,
}


def extract_ids(html):
    """IDs de listings (cardetail.cfm?c=ID) de la página actual."""
    return ID_RE.findall(html)


def find_next_url(html, current_url):
    """
    Devuelve la URL absoluta de la página siguiente, o None si no hay.
    El 'siguiente' es el <a> que contiene el ícono .fa-angle-right.
    """
    tree = HTMLParser(html)
    arrow = tree.css_first(".fa-angle-right")
    if arrow is None:
        return None
    # subir hasta el <a> que envuelve la flecha
    node = arrow
    for _ in range(4):
        if node is None:
            break
        if node.tag == "a" and node.attributes.get("href"):
            return urljoin(current_url, node.attributes["href"])
        node = node.parent
    # respaldo: el último enlace a searchresults.cfm de la página
    cands = [a.attributes.get("href") for a in tree.css("a[href*='searchresults.cfm']")
             if a.attributes.get("href")]
    return urljoin(current_url, cands[-1]) if cands else None


async def discover_crautos(limit=None, max_pages=400, delay=1.0):
    seen = {}                       # id -> url (dedupe por el c= estable del auto)
    async with httpx.AsyncClient(follow_redirects=True, timeout=30,
                                 headers=HEADERS) as client:
        # 1) nacer la cookie de sesión abriendo el form
        await client.get(urljoin(BASE, "index.cfm"))

        # 2) arrancar la búsqueda (sin filtros = todo). El server asigna el c.
        url = START
        for page_no in range(1, max_pages + 1):
            r = await client.get(url)
            html = r.text
            ids = extract_ids(html)
            nuevos = 0
            for cid in ids:
                if cid not in seen:
                    seen[cid] = urljoin(BASE, f"cardetail.cfm?c={cid}")
                    nuevos += 1
            print(f"[crautos] pág {page_no} ({url.split('?')[-1] or 'inicio'}): "
                  f"+{nuevos} nuevos, total {len(seen)}")

            if nuevos == 0 and page_no > 1:
                print("[crautos] página sin IDs nuevos, fin")
                break
            if limit and len(seen) >= limit:
                break

            nxt = find_next_url(html, str(r.url))
            if not nxt or nxt == url:
                print("[crautos] no hay enlace de siguiente, fin")
                break
            url = nxt
            await asyncio.sleep(delay)

    items = list(seen.items())
    return items[:limit] if limit else items


if __name__ == "__main__":
    async def _main():
        res = await discover_crautos(limit=150, delay=1.0)   # prueba chica
        print(f"\nDescubiertos: {len(res)}")
        for cid, u in res[:5]:
            print(" ", cid, u)
    asyncio.run(_main())
