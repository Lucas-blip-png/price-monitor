from urllib.parse import urlparse

from ..prices import Item
from . import amazon, generic, kabum, mercadolivre

_BY_HOST = (
    ("mercadolivre", mercadolivre),
    ("mercadolibre", mercadolivre),
    ("amazon.com", amazon),
    ("kabum.com.br", kabum),
)


async def fetch_item(url: str, selector: str | None = None) -> Item:
    host = urlparse(url).netloc.lower()
    store = next((m for k, m in _BY_HOST if k in host), generic)
    return await store.fetch(url, selector)
