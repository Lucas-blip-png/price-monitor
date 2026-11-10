import asyncio
import time
from types import SimpleNamespace

import pytest

from price_monitor import http, promos
from price_monitor.alerts import check_product, evaluate
from price_monitor.db import DB
from price_monitor.prices import Item, brl, find_prices, parse_price
from price_monitor.promos import Post
from price_monitor.stores import amazon
from price_monitor.stores.generic import parse_html


# --- preços -----------------------------------------------------------------
@pytest.mark.parametrize(
    "texto,esperado",
    [("R$ 1.234,56", 1234.56), ("R$ 99,90", 99.9), ("1299.90", 1299.9), ("2.499", 2499.0), ("R$ 1299", 1299.0), ("grátis", None)],
)
def test_parse_price(texto, esperado):
    assert parse_price(texto) == esperado


def test_find_prices_e_brl():
    assert find_prices("De R$ 2.499,00 por R$ 1.999 e frete R$ 9,90") == [2499.0, 1999.0, 9.9]
    assert brl(1234.5) == "R$ 1.234,50"


# --- regra de alerta --------------------------------------------------------
def test_evaluate():
    assert evaluate(90, 95, 100, None) == ("target", 90)  # atingiu o alvo
    assert evaluate(90, 95, 90, 90) == (None, 90)  # mesmo preço já avisado: sem spam
    assert evaluate(85, 95, 90, 90) == ("target", 85)  # caiu mais: avisa de novo
    assert evaluate(120, 95, 90, 90) == (None, None)  # subiu: rearma
    assert evaluate(80, None, 100, None) == ("drop", 80)  # queda >= 5% sem alvo
    assert evaluate(98, None, 100, None) == (None, None)  # queda pequena


def _fake_fetch(precos):
    it = iter(precos)

    async def fetch(url, selector=None):
        v = next(it)
        if isinstance(v, Exception):
            raise v
        return Item("Mouse", v)

    return fetch


def test_check_product_ciclo():
    db, msgs = DB(), []

    async def notify(chat, text):
        msgs.append(text)

    pid = db.add_product(1, "http://x/p", "Mouse", 100.0)
    fetch = _fake_fetch([90, 90, 120, 100])

    async def rodar():
        for _ in range(4):
            await check_product(db, fetch, notify, db.product(pid, 1))

    asyncio.run(rodar())
    # 90 (queda 10%) avisa; 90 repetido não; 120 rearma; 100 (queda 16%) avisa
    assert len(msgs) == 2 and "queda de 10%" in msgs[0] and "queda de 17%" in msgs[1]
    assert [r["price"] for r in db.history(pid)] == [100.0, 90.0, 120.0, 100.0]


def test_tres_falhas_avisam_uma_vez():
    db, msgs = DB(), []

    async def notify(chat, text):
        msgs.append(text)

    pid = db.add_product(1, "http://x/p", "Mouse", 100.0)
    fetch = _fake_fetch([http.FetchError("bloqueado")] * 4)

    async def rodar():
        for _ in range(4):
            assert await check_product(db, fetch, notify, db.product(pid, 1)) is None

    asyncio.run(rodar())
    assert len(msgs) == 1 and "3 vezes" in msgs[0]


def test_isolamento_por_chat():
    db = DB()
    pid = db.add_product(1, "http://x/p", "Mouse", 10.0)
    assert db.product(pid, 2) is None and not db.remove_product(pid, 2) and not db.set_target(pid, 2, 5)
    assert db.remove_product(pid, 1)


# --- parsers de loja --------------------------------------------------------
JSONLD = """<script type="application/ld+json">{"@graph":[{"@type":"Product","name":"Teclado X",
"offers":{"@type":"Offer","price":"349.90"}}]}</script>"""


def test_parse_html_jsonld_graph():
    assert parse_html(JSONLD) == ("Teclado X", 349.9)


def test_parse_html_seletor_tem_prioridade_e_fallback_meta():
    html = '<title>Loja</title><meta property="og:title" content="Fone"><span class="p">R$ 1.050,00</span>' + JSONLD
    assert parse_html(html, ".p")[1] == 1050.0
    meta = '<meta property="og:title" content="Fone"><meta itemprop="price" content="59.9">'
    assert parse_html(meta) == ("Fone", 59.9)


def _fake_get(html):
    async def get(url, retries=2):
        return SimpleNamespace(text=html, url=url)

    return get


def test_amazon(monkeypatch):
    ok = '<span id="productTitle"> Echo Dot </span><div id="corePrice_feature_div"><span class="a-offscreen">R$ 329,00</span></div>'
    monkeypatch.setattr(http, "get", _fake_get(ok))
    assert asyncio.run(amazon.fetch("https://www.amazon.com.br/dp/X")) == Item("Echo Dot", 329.0)
    monkeypatch.setattr(http, "get", _fake_get('<form action="/errors/validateCaptcha">'))
    with pytest.raises(http.FetchError, match="captcha"):
        asyncio.run(amazon.fetch("https://www.amazon.com.br/dp/X"))


# --- canais de promoção -----------------------------------------------------
def _canal_html(*posts):
    return "".join(
        f'<div class="tgme_widget_message" data-post="ofertas/{i}"><div class="tgme_widget_message_text">{t}</div></div>'
        for i, t in posts
    )


def test_scan_canal(monkeypatch):
    html = _canal_html((5, "velho"), (6, "Notebook Gamer R$ 3.999 imperdível"), (7, "Cafeteira por R$ 120"))
    monkeypatch.setattr(http, "get", _fake_get(html))
    db, msgs = DB(), []

    async def notify(chat, text):
        msgs.append((chat, text))

    db.add_channel(1, "ofertas", 5)  # posts <= 5 já eram vistos
    db.add_keyword(1, "Cafeteira")
    asyncio.run(promos.scan(db, notify))
    assert len(msgs) == 1 and "R$ 120,00" in msgs[0][1] and msgs[0][1].endswith("https://t.me/ofertas/7")
    asyncio.run(promos.scan(db, notify))  # sem repetir
    assert len(msgs) == 1


def test_match_post_por_produto():
    prods = [{"title": "Mouse Gamer Logitech G203 Preto", "last_price": 200.0}]
    reason, prod = promos.match_post("Mouse Gamer Logitech G203 com desconto", [], prods)
    assert "produto" in reason and prod is prods[0]
    assert promos.match_post("Geladeira em oferta", [], prods) is None
    assert promos.match_post("Cafeteira barata", ["cafeteira"], prods)[1] is None


def test_best_price():
    assert promos.best_price("Notebook de R$ 4.999 por R$ 3.799 em 10x de R$ 379,90") == 3799.0
    assert promos.best_price("Mouse R$ 120 + frete R$ 9,90") == 120.0  # sem 'por': o maior
    assert promos.best_price("Fone à vista R$ 1.800 ou 12x de R$ 199") == 1800.0  # parcela ignorada
    assert promos.best_price("Camisa ❌ De: R$79,90 ✅ Por: R$28,90 🔻 64% de desconto") == 28.9  # post real
    assert promos.best_price("sem preço aqui") is None


def test_melhor_compara_canais_e_produtos(monkeypatch):
    agora = time.time()
    posts = [
        Post(1, "Mouse Logitech G203 por R$ 150", agora - 3600),
        Post(2, "Mouse Logitech G203 por R$ 120", agora - 2 * 86400),
        Post(3, "Teclado Redragon por R$ 90", agora),
    ]

    async def fake_get(url, retries=2):
        return SimpleNamespace(text=_canal_html(*[(p.id, p.text) for p in posts]), url=url)

    monkeypatch.setattr(http, "get", fake_get)
    db = DB()
    db.add_product(1, "https://www.kabum.com.br/p/1", "Mouse Gamer Logitech G203 Preto", 200.0)
    db.add_channel(1, "ofertas", 99)  # nada é "novo": só /melhor usa os posts
    asyncio.run(promos.scan(db, lambda c, t: None))
    deals = promos.best_deals(db, 1, "logitech g203")
    assert [d.price for d in deals] == [120.0, 150.0, 200.0]
    assert deals[0].link == "https://t.me/ofertas/2" and "kabum.com.br" in deals[2].source
    assert promos.best_deals(db, 1, "geladeira") == [] and promos.best_deals(db, 1, "") == []
    assert promos.best_deals(db, 2, "logitech g203") == []  # outro chat não vê nada


def test_aviso_mais_barato_que_o_seu(monkeypatch):
    monkeypatch.setattr(http, "get", _fake_get(_canal_html((7, "Mouse Gamer Logitech G203 Preto por R$ 150"))))
    db, msgs = DB(), []

    async def notify(chat, text):
        msgs.append(text)

    db.add_product(1, "http://x/p", "Mouse Gamer Logitech G203 Preto", 200.0)
    db.add_channel(1, "ofertas", 0)
    asyncio.run(promos.scan(db, notify))
    assert len(msgs) == 1 and "R$ 150,00" in msgs[0] and "mais barato que o seu preço atual (R$ 200,00)" in msgs[0]
