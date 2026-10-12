from .. import http
from ..prices import Item
from .generic import parse_html

PRICE = "#corePrice_feature_div span.a-offscreen, span.a-price span.a-offscreen"


async def fetch(url: str, selector=None) -> Item:
    html = (await http.get(url)).text
    if "validateCaptcha" in html or "Digite os caracteres" in html:
        raise http.FetchError("Amazon pediu captcha (bloqueio anti-bot); tente mais tarde")
    title, price = parse_html(html, selector or PRICE, "#productTitle")
    if price is None:
        raise http.FetchError("Amazon: preço não encontrado (produto indisponível?)")
    return Item(title or url, price)
