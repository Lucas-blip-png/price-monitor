import asyncio
import time
from urllib.parse import urlparse

import httpx

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"
)
MIN_GAP = 2.0  # segundos entre requisições ao mesmo domínio
RETRY_STATUS = {429, 500, 502, 503, 504}


class FetchError(Exception):
    pass


_last: dict[str, float] = {}
_lock = asyncio.Lock()


async def _wait(host: str) -> None:
    async with _lock:
        now = time.monotonic()
        slot = max(now, _last.get(host, 0) + MIN_GAP)
        _last[host] = slot
    if slot > now:
        await asyncio.sleep(slot - now)


async def get(url: str, retries: int = 2) -> httpx.Response:
    host = urlparse(url).netloc
    err = "?"
    for i in range(retries + 1):
        await _wait(host)
        try:
            async with httpx.AsyncClient(
                headers={"User-Agent": UA, "Accept-Language": "pt-BR,pt;q=0.9"},
                follow_redirects=True,
                timeout=20,
            ) as c:
                r = await c.get(url)
            if r.status_code < 400:
                return r
            err = f"HTTP {r.status_code}"
            if r.status_code not in RETRY_STATUS:
                break
        except httpx.HTTPError as e:
            err = str(e) or type(e).__name__
        await asyncio.sleep(2**i)
    raise FetchError(f"{host}: {err}")
