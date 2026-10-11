"""Generic Open Graph resolver — last-resort fallback for any URL.

Useful if a listing comes from a site we don't have a specific resolver for.
Extracts og:title, og:image, og:description and tries to regex-extract
year/km/price/make from the title.
"""
from __future__ import annotations
import re
import json
import httpx
from bs4 import BeautifulSoup
from .base import Listing, Field
from .. import parsers

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


def _meta(html: str, prop: str) -> str | None:
    """Support normal HTML attribute ordering and both quote styles."""
    soup = BeautifulSoup(html, "html.parser")
    tag = soup.find("meta", attrs={"property": prop}) or soup.find("meta", attrs={"name": prop})
    value = tag.get("content") if tag else None
    return str(value).strip() if value else None


def _structured_price(html: str, *, allow_unescaped_controls: bool = False) -> float | None:
    """Extract a USD vehicle offer, with a narrow Julajups control-char repair.

    Some Julajups pages embed literal newlines in JSON-LD description strings.
    json.loads(strict=False) accepts those controls without changing the price
    or accepting unrelated invalid JSON structure. Keep other sites strict.
    """
    soup = BeautifulSoup(html, "html.parser")
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        try:
            root = json.loads(script.string or script.get_text(), strict=not allow_unescaped_controls)
        except (ValueError, TypeError):
            continue
        todo = [root]
        while todo:
            obj = todo.pop()
            if isinstance(obj, list):
                todo.extend(obj)
                continue
            if not isinstance(obj, dict):
                continue
            todo.extend(obj.get("@graph", []) if isinstance(obj.get("@graph"), list) else [])
            kind = obj.get("@type")
            kinds = [str(item).lower() for item in kind] if isinstance(kind, list) else [str(kind).lower()]
            if not any(k in {"product", "vehicle", "car"} for k in kinds):
                continue
            offers = obj.get("offers")
            if isinstance(offers, list):
                offers = next((o for o in offers if isinstance(o, dict)), None)
            if not isinstance(offers, dict):
                continue
            if str(offers.get("priceCurrency") or "").upper() != "USD":
                continue
            raw = offers.get("price")
            try:
                price = float(str(raw).replace(",", ""))
            except (ValueError, TypeError):
                continue
            if 500 <= price <= 200000:
                return price
    return None

async def resolve(url: str) -> Listing:
    listing = Listing(platform="unknown", url=url)

    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=False,
                                     headers={"User-Agent": USER_AGENT}) as cli:
            r = await cli.get(url)
            # Avoid automatic cross-origin redirects (SSRF and provenance confusion).
            if 300 <= r.status_code < 400:
                listing.errors.append("redirect not followed; source requires review")
                return listing
            if r.status_code >= 400:
                listing.errors.append(f"http {r.status_code}")
                return listing
            html = r.text
    except httpx.HTTPError as e:
        listing.errors.append(f"http error: {e!s}")
        return listing

    return parse_html(url, html)


def _carroselsalvador_detail(html: str, listing: Listing) -> None:
    """Parse only the heading-adjacent price and labelled odometer on this domain."""
    from urllib.parse import urlparse
    host = (urlparse(listing.url).hostname or "").lower().removeprefix("www.")
    if host != "carroselsalvador.com":
        return
    soup = BeautifulSoup(html, "html.parser")
    h1 = soup.find("h1")
    if not h1:
        return
    title = h1.get_text(" ", strip=True)
    if not re.search(r"\b(?:19|20)\d{2}\b", title):
        return
    for node in h1.find_all_previous(string=True, limit=24):
        match = re.fullmatch(r"\s*US\s*\$\s*([\d,]+)(?:\.00)?\s*", str(node), re.I)
        if match:
            price = int(match.group(1).replace(",", ""))
            if 500 <= price <= 200000:
                listing.price_usd = Field(value=price, confidence="medium")
                break
    text = soup.get_text(" ", strip=True)
    mileage = re.search(r"\bRecorrido\s*:?\s*([\d.,]+)\s*(mi|millas|km)\b", text, re.I)
    if mileage:
        raw = mileage.group(1).replace(",", "")
        try:
            distance = float(raw)
        except ValueError:
            return
        if 0 <= distance <= 2000000:
            km = round(distance * 1.609344) if mileage.group(2).lower() != "km" else round(distance)
            listing.km = Field(value=km, confidence="medium")

def _experimental_listing_detail(html: str, listing: Listing) -> None:
    """Site-local price/mileage, excluding related ads and seller free-text.

    These branches are exploratory: absence of authoritative listing-local price
    must stay missing, never fall back to a related-car or financing installment.
    """
    from urllib.parse import urlparse
    host = (urlparse(listing.url).hostname or "").lower().removeprefix("www.")
    if host not in {"tucarro.sv", "caragencia.com", "carros.com"}:
        return
    soup = BeautifulSoup(html, "html.parser")
    h1 = soup.find("h1")
    if not h1:
        return
    text = soup.get_text(" ", strip=True)
    title = h1.get_text(" ", strip=True)
    if not re.search(r"\b(?:19|20)\d{2}\b", title):
        return

    price_match = None
    miles_match = None
    if host == "tucarro.sv":
        # Only the immediate heading-area facts, before seller notes/financing.
        next_fragments = [str(v).strip() for v in h1.find_all_next(string=True, limit=35)]
        facts = " ".join(next_fragments)
        price_match = re.search(r"(?<!\w)\$\s*([\d,]{3,})(?!\d)", facts)
        miles_match = re.search(r"\b([\d,]{2,})\s*(km|millas|mi)\b", facts, re.I)
    elif host == "caragencia.com":
        # Authoritative listing price, not the seller's arbitrary notes.
        price_match = re.search(r"\bListing Price\s+USD\s*([\d,]+)", text, re.I)
        # If the listing explicitly says miles we may normalize them.
        note = re.search(r"\bSeller notes\b(.{0,2500}?)\bListing Price\b", text, re.I | re.S)
        if note:
            miles_match = re.search(r"(?<![\d,])(\d[\d,]*)\s*(millas|mi|km)\b", note.group(1), re.I)
    else:  # carros.com
        # Carros.com includes classic 1980s vehicles; generic year parser starts
        # at 1990. Only accept the year between separators in THIS vehicle's H1.
        exact_year = re.search(r"[•·]\s*((?:19|20)\d{2})\s*[•·]", title)
        if exact_year and 1950 <= int(exact_year.group(1)) <= 2035:
            listing.year = Field(value=int(exact_year.group(1)), confidence="high")
        # Use only the current page's header and Vehicle Details block.
        lead = text.split("Vehicle Details", 1)[0][:1600]
        price_match = re.search(r"\$\s*([\d,]+)\s*USD\b", lead, re.I)
        details = text.split("Vehicle Details", 1)
        if len(details) == 2:
            details = details[1].split("Description", 1)[0]
            miles_match = re.search(r"\bMileage\s*([\d,]+)\s*(km|mi|millas)\b", details, re.I)
    if price_match:
        try:
            price = int(price_match.group(1).replace(",", ""))
        except (ValueError, TypeError):
            price = None
        if price is not None and 500 <= price <= 200000:
            listing.price_usd = Field(value=price, confidence="medium")
    if host == "carros.com":
        # Prefer the listing's exact gallery over relative/default OG image.
        # Gallery photos may use protocol-relative or site-relative URLs.
        from urllib.parse import urljoin, urlparse as _urlparse, urlunparse
        display_name = h1.get_text(" ", strip=True).split("•")[0].strip().lower()
        for img in soup.select("img.gallery-img"):
            raw = str(img.get("src") or "").strip()
            alt = str(img.get("alt") or "").strip().lower()
            if not raw or not display_name or not alt.startswith(display_name):
                continue
            photo = urljoin("https://carros.com/", raw)
            p = _urlparse(photo)
            if (p.hostname or "").lower() not in {"carros.com", "www.carros.com"}:
                continue
            if p.scheme == "http":
                photo = urlunparse(p._replace(scheme="https"))
                p = _urlparse(photo)
            if p.scheme == "https":
                listing.photos = [photo]
                break
    if miles_match:
        try:
            amount = int(miles_match.group(1).replace(",", ""))
            unit = miles_match.group(2).lower()
        except (ValueError, IndexError):
            amount = None
            unit = None
        if amount is not None and 0 <= amount <= 2000000:
            listing.km = Field(value=round(amount * 1.609344) if unit != "km" else amount,
                               confidence="medium")


def _autospublicidad_detail(html: str, listing: Listing) -> None:
    """Use only one AutosPublicidad vehicle's local gallery and explicit miles.

    The listing's 'Kilometraje 67' alone does not tell us the unit. Only a
    seller note explicitly saying '67 mil millas' justifies a conversion.
    """
    from urllib.parse import parse_qs, urljoin, urlparse

    parsed = urlparse(listing.url)
    host = (parsed.hostname or "").lower().removeprefix("www.")
    if host != "autospublicidad.com" or parsed.path.rstrip("/") != "/sv/detalles":
        return
    query = parse_qs(parsed.query)
    source_id = (query.get("id") or [None])[0]
    if not source_id or not re.fullmatch(r"[1-9][0-9]{0,6}", source_id):
        return
    soup = BeautifulSoup(html, "html.parser")
    title = str(listing.title.value if listing.title else "").lower()
    if not title:
        return
    for image in soup.select("img[src]"):
        raw = str(image.get("src") or "").strip()
        alt = str(image.get("alt") or "").lower()
        alt_match = re.fullmatch(r"imagen\s*[1-9][0-9]*\s+del\s+(.+)", alt, re.I)
        if not raw or not alt_match:
            continue
        vehicle_name = re.findall(r"[a-záéíóúñ0-9]+", alt_match.group(1).lower())
        # Match the specific make/model from the image's own alt text.
        if not vehicle_name or not all(token in title for token in vehicle_name[:3]):
            continue
        url = urljoin(listing.url, raw)
        p = urlparse(url)
        if p.scheme != "https" or (p.hostname or "").lower().removeprefix("www.") != host:
            continue
        if not re.fullmatch(
            rf"/sv/images/autos/{re.escape(source_id)}/[^/]+\.(?:jpg|jpeg|png|webp)",
            p.path,
            re.I,
        ):
            continue
        listing.photos = [url]
        break

    # Seller note includes an explicit unit: "67 mil millas".
    text = soup.get_text(" ", strip=True)
    seller_section = text.split("Información de venta", 1)[-1].split("Contacto", 1)[0]
    miles = re.search(r"\b([1-9][0-9]{0,2})\s+mil\s+millas\b", seller_section, re.I)
    if miles:
        number_of_miles = int(miles.group(1)) * 1000
        if number_of_miles <= 500000:
            listing.km = Field(value=round(number_of_miles * 1.609344),
                               confidence="medium")


def _carvimax_listing_mileage(html: str, listing: Listing) -> None:
    """Normalize only explicitly unit-labelled Carvimax listing metadata.

    Do not guess units from bare vehicle-detail numbers or related vehicles.
    """
    from urllib.parse import urlparse
    host = (urlparse(listing.url).hostname or "").lower().removeprefix("www.")
    if host != "carvimax.com" or not listing.title:
        return
    # The site's /og/vehicle/ endpoint may not serve a renderable photo.
    # Prefer the current vehicle gallery's real HTTPS CDN image, never related ads.
    from urllib.parse import urlparse as _parse
    soup = BeautifulSoup(html, "html.parser")
    title = str(listing.title.value).strip().lower()
    make = re.match(r"[a-z]+", title)
    for img in soup.select("img[src]"):
        photo = str(img.get("src") or "").strip()
        alt = str(img.get("alt") or "").strip().lower()
        parsed = _parse(photo)
        if (make and alt == make.group(0)
            and parsed.scheme == "https"
            and parsed.hostname == "carvimax-prod-aws-bucket.s3.us-west-2.amazonaws.com"
            and parsed.path.startswith("/web-marketplace/uploads/vehicle-images/")
            and len(parsed.path.split("/")[-1]) >= 16):
            listing.photos = [photo]
            break
    description = _meta(html, "og:description") or ""
    mileage = re.search(r"\b([1-9][0-9,]{0,8})\s*(mi|millas|km)\b", description, re.I)
    if not mileage:
        return
    try:
        value = int(mileage.group(1).replace(",", ""))
    except ValueError:
        return
    if value > 500000:
        return
    unit = mileage.group(2).lower()
    listing.km = Field(
        value=round(value * 1.609344) if unit in {"mi", "millas"} else value,
        confidence="medium",
    )


def _anuto_listing_detail(html: str, listing: Listing) -> None:
    """Read the named vehicle's own detail section on Anuto SV.

    The seller's free-text description can contradict labelled odometer data,
    and related vehicles appear later on the page. Only extract the listing's
    own 'Detalles' labels before 'Descripción', not related ads.
    """
    from urllib.parse import urlparse
    p = urlparse(listing.url)
    if (p.hostname or "").lower() != "sv.anuto.app" or not p.path.startswith("/ad/"):
        return
    soup = BeautifulSoup(html, "html.parser")
    h1 = soup.find("h1")
    if h1:
        name = h1.get_text(" ", strip=True)
        if 5 <= len(name) <= 180:
            listing.title = Field(value=name, confidence="high")
    text = soup.get_text(" ", strip=True)
    segments = re.split(r"\bDetalles\b", text, maxsplit=1, flags=re.I)
    if len(segments) < 2:
        return
    segment = re.split(r"\bDescripci[oó]n\b", segments[1], maxsplit=1, flags=re.I)[0][:1300]
    year_match = re.search(r"\bA[nñ]o\s*:?\s*((?:19|20)\d{2})\b", segment, re.I)
    if year_match:
        listing.year = Field(value=int(year_match.group(1)), confidence="high")
    km_match = re.search(r"\bKil[oó]metros\s*:?\s*([0-9][0-9.,]{0,11})\s*(?:km|kms)\b",
                         segment, re.I)
    if km_match:
        try:
            km = int(km_match.group(1).replace(",", "").replace(".", ""))
        except ValueError:
            return
        if 0 <= km <= 2_000_000:
            listing.km = Field(value=km, confidence="medium")


def _excel_usados_listing_detail(html: str, listing: Listing) -> None:
    """Extract one Excel Usados vehicle, using only the local listing section.

    This WordPress template has no OG fields on vehicle pages. The actual
    vehicle is the single H1, price label under div.layer, feature labels
    after the H1, and its own div.item upload gallery. If any required fact
    is missing (sold/removed listing), fail closed rather than using Atlas
    inventory or asking prices from another vehicle.
    """
    from urllib.parse import urlparse, urljoin

    parsed = urlparse(listing.url)
    if (parsed.hostname or "").lower() != "usados.excelautomotriz.com" or not re.fullmatch(
        r"/autos-el-salvador/[a-z0-9][a-z0-9-]+/?", parsed.path, re.I
    ):
        return
    # Reject generic/related-ad metadata when the individual vehicle price is absent.
    listing.title = None
    listing.price_usd = None
    listing.year = None
    listing.km = None
    listing.photos = []
    soup = BeautifulSoup(html, "html.parser")
    headings = soup.select("h1")
    if len(headings) != 1:
        return
    title = headings[0].get_text(" ", strip=True)
    if not (5 <= len(title) <= 180):
        return

    # There is exactly one individual listing heading on these pages.
    parts = soup.get_text(" ", strip=True).split(title, 1)
    if len(parts) != 2:
        return
    local = re.split(r"\bSOLICITA\s+TU\s+CITA\b", parts[1], maxsplit=1, flags=re.I)[0][:1600]
    label_price = re.search(r"\bPrecio\s*\$\s*([0-9][0-9,.]{2,12})\b", local, re.I)
    label_year = re.search(r"\bA[nñ]o\s*:?\s*((?:19|20)\d{2})\b", local, re.I)
    label_km = re.search(r"\bRecorrido\s*:?\s*([0-9][0-9,.]{0,12})\s*(Kil[oó]metros|km)\b", local, re.I)
    if not label_price or not label_year:
        return
    try:
        price = int(label_price.group(1).replace(",", "").replace(".", ""))
        year = int(label_year.group(1))
    except ValueError:
        return
    if not 500 <= price <= 200000 or not 1990 <= year <= 2035:
        return

    listing.title = Field(value=title, confidence="high")
    listing.price_usd = Field(value=price, confidence="high")
    listing.year = Field(value=year, confidence="high")

    if label_km:
        try:
            km = int(label_km.group(1).replace(",", "").replace(".", ""))
            if 0 <= km <= 2_000_000:
                listing.km = Field(value=km, confidence="high")
        except ValueError:
            pass

    # Gallery images are served from the actual Excel site, not logos/menus.
    # The first vehicle slide is enough for Carly; don't download or persist.
    for img in soup.select("div.item img[src]"):
        raw = (img.get("src") or "").strip()
        url = urljoin(listing.url, raw)
        p = urlparse(url)
        if (p.scheme == "https" and
            (p.hostname or "").lower() == "usados.excelautomotriz.com" and
            p.path.startswith("/wp-content/uploads/") and
            re.search(r"\.(?:jpe?g|png|webp)$", p.path, re.I)):
            listing.photos = [url]
            break


def parse_html(url: str, html: str) -> Listing:
    """Parse already-fetched HTML without additional outbound network requests."""
    listing = Listing(platform="unknown", url=url)
    og_title = _meta(html, "og:title") or _meta(html, "twitter:title") or ""
    og_image = _meta(html, "og:image") or _meta(html, "twitter:image") or ""
    og_desc = _meta(html, "og:description") or _meta(html, "twitter:description") or ""

    if og_title:
        listing.title = Field(value=og_title.strip()[:200], confidence="medium")
    if og_image:
        listing.photos.append(og_image)
    if og_desc:
        listing.description = Field(value=og_desc.strip()[:500], confidence="medium")

    haystack = (og_title + " " + og_desc).strip()
    yr = parsers.extract_year(haystack)
    if yr:
        listing.year = Field(value=yr[0], confidence="low")
    km = parsers.extract_km(haystack)
    if km:
        listing.km = Field(value=km[0], confidence="low")
    from urllib.parse import urlparse
    source_host = (urlparse(url).hostname or "").lower().removeprefix("www.")
    structured_price = _structured_price(
        html,
        allow_unescaped_controls=(source_host == "julajups.sv"),
    )
    if structured_price is not None:
        listing.price_usd = Field(value=structured_price, confidence="high")
    pr = parsers.extract_price_usd(og_title) if structured_price is None else None
    if pr:
        listing.price_usd = Field(value=pr[0], confidence="low")
    mk = parsers.extract_make(haystack)
    if mk:
        listing.make = Field(value=mk[0], confidence="medium")
        md = parsers.extract_model(haystack, mk[0])
        if md:
            listing.model = Field(value=md[0], confidence="low")

    _carroselsalvador_detail(html, listing)
    _experimental_listing_detail(html, listing)
    _autospublicidad_detail(html, listing)
    _carvimax_listing_mileage(html, listing)
    _anuto_listing_detail(html, listing)
    _excel_usados_listing_detail(html, listing)
    return listing
