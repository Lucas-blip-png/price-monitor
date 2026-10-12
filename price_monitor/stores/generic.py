import json

from bs4 import BeautifulSoup

from .. import http
from ..prices import Item, parse_price


def _num(v) -> float | None:
    if isinstance(v, (int, float)):
        return float(v) or None
    return parse_price(v) if v else None


def _products(soup):
    """Itens JSON-LD do tipo Product (inclusive dentro de @graph/listas)."""
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            stack = [json.loads(tag.string or "")]
        except ValueError:
            continue
        while stack:
            d = stack.pop()
            if isinstance(d, list):
                stack.extend(d)
            elif isinstance(d, dict):
                stack.append(d.get("@graph", []))
                t = d.get("@type")
                if t == "Product" or (isinstance(t, list) and "Product" in t):
                    yield d


def _offer_price(offers) -> float | None:
    if isinstance(offers, dict):
        offers = [offers]
    prices = [
        p
        for o in offers or []
        if isinstance(o, dict)
        for p in [_num(o.get("price")) or _num(o.get("lowPrice"))]
        if p
    ]
    return min(prices) if prices else None


def parse_html(html: str, selector=None, title_selector=None) -> tuple[str | None, float | None]:
    """Preço por: seletor do usuário > JSON-LD Product > meta tags. Título idem."""
    soup = BeautifulSoup(html, "html.parser")
    title = price = None
    if selector and (el := soup.select_one(selector)):
        price = parse_price(el.get("content") or el.get_text())
    if title_selector and (el := soup.select_one(title_selector)):
        title = el.get_text(strip=True)
    for d in _products(soup):
        title = title or d.get("name")
        price = price or _offer_price(d.get("offers"))
    if price is None:
        m = soup.find("meta", attrs={"property": "product:price:amount"}) or soup.find(
            "meta", attrs={"itemprop": "price"}
        )
        price = parse_price(m.get("content")) if m else None
    if not title:
        m = soup.find("meta", attrs={"property": "og:title"})
        title = m.get("content") if m else (soup.title.string.strip() if soup.title and soup.title.string else None)
    return title, price


async def fetch(url: str, selector=None) -> Item:
    title, price = parse_html((await http.get(url)).text, selector)
    if price is None:
        raise http.FetchError(
            "preço não encontrado na página; informe o seletor CSS: /add <url> css=<seletor>"
        )
    return Item(title or url, price)
