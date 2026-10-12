import re
import time
from datetime import datetime
from typing import NamedTuple
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from . import http
from .prices import brl, find_prices

KEEP_DAYS = 30  # quanto tempo os posts ficam guardados para o /melhor


class Post(NamedTuple):
    id: int
    text: str
    ts: float = 0.0


class Deal(NamedTuple):
    price: float
    source: str
    link: str
    ts: float


async def fetch_channel(name: str) -> list[Post]:
    """Posts recentes de um canal PÚBLICO via preview web (https://t.me/s/<canal>), sem login."""
    soup = BeautifulSoup((await http.get(f"https://t.me/s/{name}")).text, "html.parser")
    posts = []
    for m in soup.select("div.tgme_widget_message[data-post]"):
        body = m.select_one("div.tgme_widget_message_text")
        if not body:
            continue
        t = m.select_one("time[datetime]")
        try:
            ts = datetime.fromisoformat(t["datetime"]).timestamp() if t else 0.0
        except ValueError:
            ts = 0.0
        posts.append(Post(int(m["data-post"].rsplit("/", 1)[1]), body.get_text(" ", strip=True), ts))
    return posts


_PARCELA = re.compile(r"\d+\s*x\s*(?:de\s*)?R\$\s*[\d.,]+", re.I)  # "10x de R$ 199" não é o preço
_POR = re.compile(r"\bpor\s*:?\s*(R\$\s*[\d.,]+)", re.I)


def best_price(text: str) -> float | None:
    """Preço da oferta num post: o valor depois de 'por', senão o maior (ignora parcelas)."""
    # ponytail: heurística; cupons/frete soltos podem enganar. Trocar por regras por canal se precisar.
    text = _PARCELA.sub(" ", text)
    if (m := _POR.search(text)) and (p := find_prices(m[1])):
        return p[0]
    prices = find_prices(text)
    return max(prices) if prices else None


def _tokens(s: str) -> set[str]:
    return {t for t in re.findall(r"\w+", s.casefold()) if len(t) > 2}


def match_post(text: str, keywords: list[str], products) -> tuple[str, object | None] | None:
    """(motivo, produto|None) se o post interessa, senão None. Produto = 60% dos termos do título."""
    low = text.casefold()
    for k in keywords:
        if k in low:
            return f"palavra «{k}»", None
    post = _tokens(text)
    for p in products:
        tok = _tokens(p["title"])
        # ponytail: heurística de interseção de termos; trocar por busca difusa se der falso positivo
        if tok and len(tok & post) / len(tok) >= 0.6:
            return f"produto «{p['title'][:40]}»", p
    return None


def format_post(name: str, post: Post, reason: str, product=None) -> str:
    price = best_price(post.text)
    head = f"🏷️ Promoção em @{name} ({reason})" + (f" · {brl(price)}" if price else "")
    if product and price and product["last_price"] and price < product["last_price"]:
        head += f"\n🔥 mais barato que o seu preço atual ({brl(product['last_price'])})"
    return f"{head}\n{post.text[:400]}\nhttps://t.me/{name}/{post.id}"


def remember(db, chat, name, posts) -> None:
    """Guarda os posts (com preço extraído) para o /melhor consultar depois."""
    for p in posts:
        db.save_post(chat, name, p.id, p.text, best_price(p.text), p.ts or time.time())


def best_deals(db, chat, term: str, days: int = KEEP_DAYS, limit: int = 5) -> list[Deal]:
    """Ofertas mais baratas para `term`: posts dos canais + seus produtos monitorados."""
    want = _tokens(term)
    if not want:
        return []
    deals = [
        Deal(r["price"], f"@{r['channel']}", f"https://t.me/{r['channel']}/{r['post_id']}", r["ts"])
        for r in db.posts_since(chat, time.time() - days * 86400)
        if want <= _tokens(r["text"])
    ]
    deals += [
        Deal(p["last_price"], f"seu #{p['id']} · {urlparse(p['url']).netloc}", p["url"], time.time())
        for p in db.products(chat)
        if p["last_price"] and want <= _tokens(p["title"])
    ]
    return sorted(deals, key=lambda d: d.price)[:limit]


async def scan(db, notify) -> None:
    """Para cada canal inscrito, guarda os posts e avisa os novos que casam com palavras/produtos."""
    for ch in db.channels():
        chat, name = ch["chat_id"], ch["name"]
        try:
            posts = await fetch_channel(name)
        except http.FetchError:
            continue
        remember(db, chat, name, posts)
        new = [p for p in posts if p.id > ch["last_post_id"]]
        if not new:
            continue
        db.set_last_post(chat, name, max(p.id for p in new))
        keywords, products = db.keywords(chat), db.products(chat)
        for post in new:
            if hit := match_post(post.text, keywords, products):
                await notify(chat, format_post(name, post, *hit))
    db.purge_posts(time.time() - KEEP_DAYS * 86400)
