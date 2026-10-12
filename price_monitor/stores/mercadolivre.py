import os
import re

import httpx

from .. import http
from ..prices import Item
from .generic import parse_html

_ID = re.compile(r"MLB-?(\d{6,})")


async def _api(item_id: str, token: str) -> Item:
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.get(
            f"https://api.mercadolibre.com/items/MLB{item_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
    r.raise_for_status()
    d = r.json()
    return Item(d["title"], float(d["price"]))


async def fetch(url: str, selector=None) -> Item:
    # A API pública exige token (403 sem ele) e a página costuma redirecionar
    # clientes HTTP para "account-verification". Token opcional via ML_ACCESS_TOKEN.
    token, m = os.getenv("ML_ACCESS_TOKEN"), _ID.search(url)
    if token and m:
        try:
            return await _api(m[1], token)
        except (httpx.HTTPError, KeyError, ValueError):
            pass
    r = await http.get(url)
    if "account-verification" in str(r.url):
        raise http.FetchError(
            "Mercado Livre bloqueou o acesso automático (verificação de conta); "
            "configure ML_ACCESS_TOKEN ou use os canais de promoção"
        )
    title, price = parse_html(r.text, selector)
    if price is None:
        raise http.FetchError("Mercado Livre: preço não encontrado na página")
    return Item(title or url, price)
