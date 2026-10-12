import re
from typing import NamedTuple

from bs4 import BeautifulSoup

from . import http
from .prices import brl, find_prices


class Post(NamedTuple):
    id: int
    text: str


async def fetch_channel(name: str) -> list[Post]:
    """Posts recentes de um canal PÚBLICO via preview web (https://t.me/s/<canal>), sem login."""
    soup = BeautifulSoup((await http.get(f"https://t.me/s/{name}")).text, "html.parser")
    posts = []
    for m in soup.select("div.tgme_widget_message[data-post]"):
        body = m.select_one("div.tgme_widget_message_text")
        if body:
            posts.append(Post(int(m["data-post"].rsplit("/", 1)[1]), body.get_text(" ", strip=True)))
    return posts


def _tokens(s: str) -> set[str]:
    return {t for t in re.findall(r"\w+", s.casefold()) if len(t) > 2}


def match_post(text: str, keywords: list[str], titles: list[str]) -> str | None:
    """Motivo pelo qual o post interessa, ou None. Palavra-chave = substring; produto = 60% dos termos."""
    low = text.casefold()
    for k in keywords:
        if k in low:
            return f"palavra «{k}»"
    post = _tokens(text)
    for t in titles:
        tok = _tokens(t)
        # ponytail: heurística de interseção de termos; trocar por busca difusa se der falso positivo
        if tok and len(tok & post) / len(tok) >= 0.6:
            return f"produto «{t[:40]}»"
    return None


def format_post(name: str, post: Post, reason: str) -> str:
    prices = find_prices(post.text)
    price = f" · a partir de {brl(min(prices))}" if prices else ""
    return f"🏷️ Promoção em @{name} ({reason}){price}\n{post.text[:400]}\nhttps://t.me/{name}/{post.id}"


async def scan(db, notify) -> None:
    """Para cada canal inscrito, avisa os posts novos que casam com palavras-chave/produtos."""
    for ch in db.channels():
        chat, name = ch["chat_id"], ch["name"]
        try:
            posts = [p for p in await fetch_channel(name) if p.id > ch["last_post_id"]]
        except http.FetchError:
            continue
        if not posts:
            continue
        db.set_last_post(chat, name, max(p.id for p in posts))
        keywords = db.keywords(chat)
        titles = [p["title"] for p in db.products(chat)]
        for post in posts:
            if reason := match_post(post.text, keywords, titles):
                await notify(chat, format_post(name, post, reason))
