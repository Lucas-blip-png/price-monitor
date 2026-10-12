"""Ponta a ponta do bot: handlers reais, Telegram e lojas falsos (sem rede)."""
import asyncio
import time

from telegram import Bot, User
from telegram import Update
from telegram.ext import ApplicationBuilder

from price_monitor import bot as botmod
from price_monitor import http
from price_monitor.prices import Item
from price_monitor.promos import Post

DONO = 1


class FakeBot(Bot):
    def __init__(self):
        super().__init__("123:TEST")
        self._sent: list[tuple[int, str]] = []

    async def initialize(self):
        self._bot_user, self._initialized = User(123, "pm", True, username="pm_bot"), True

    async def shutdown(self):
        pass

    async def send_message(self, chat_id, text, *a, **kw):
        self._sent.append((chat_id, text))


def test_fluxo_completo(tmp_path, monkeypatch):
    preco = {"v": 1019.9}

    async def fake_fetch(url, selector=None):
        if "quebrado" in url:
            raise http.FetchError("loja fora do ar")
        return Item("Mouse Logitech", preco["v"])

    async def fake_canal(name):
        return [Post(10, "Mouse Logitech em oferta por R$ 800", time.time())]

    monkeypatch.setattr(botmod, "fetch_item", fake_fetch)
    monkeypatch.setattr(botmod.promos, "fetch_channel", fake_canal)

    fake = FakeBot()
    app = botmod.build_app(ApplicationBuilder().bot(fake), [DONO], str(tmp_path / "t.db"))
    n = 0

    async def say(chat, text):
        """Manda uma mensagem e devolve o que o bot respondeu."""
        nonlocal n
        n += 1
        msg = {"message_id": n, "date": int(time.time()), "chat": {"id": chat, "type": "private"},
               "from": {"id": chat, "is_bot": False, "first_name": "T"}, "text": text}
        if text.startswith("/"):
            msg["entities"] = [{"type": "bot_command", "offset": 0, "length": len(text.split()[0])}]
        before = len(fake._sent)
        await app.process_update(Update.de_json({"update_id": n, "message": msg}, fake))
        return "\n".join(t for _, t in fake._sent[before:])

    async def rodar():
        await app.initialize()
        # chat fora da lista: silêncio total
        assert await say(999, "/start") == ""
        assert "Monitor de preços" in await say(DONO, "/start")
        # colar link = /add
        r = await say(DONO, "https://www.kabum.com.br/produto/1006946/mouse")
        assert "✅ #1 Mouse Logitech" in r and "R$ 1.019,90" in r
        assert "#1 Mouse Logitech" in await say(DONO, "/list")
        # alvo + queda de preço + /check dispara alerta
        assert "R$ 900,00" in await say(DONO, "/target #1 900")
        preco["v"] = 850.0
        r = await say(DONO, "/check")
        assert "atingiu seu alvo de R$ 900,00" in r and "#1 R$ 850,00" in r
        assert "mín R$ 850,00" in await say(DONO, "/history #1")
        # /check de novo não repete o alerta
        assert "atingiu" not in await say(DONO, "/check")
        # canais e palavras-chave
        assert "Monitorando @ofertas" in await say(DONO, "/canal add @Ofertas")
        assert "@ofertas" in await say(DONO, "/canal list")
        r = await say(DONO, "/melhor mouse logitech")  # post do canal (800) vence o seu produto (850)
        assert r.index("R$ 800,00") < r.index("R$ 850,00") and "@ofertas" in r and "seu #1" in r
        assert "Uso:" in await say(DONO, "/melhor")
        assert "cafeteira" in await say(DONO, "/palavra add Cafeteira") + await say(DONO, "/palavra list")
        assert "Uso:" in await say(DONO, "/canal add ../etc")  # nome inválido é recusado
        # erro de loja vira mensagem, não exceção
        assert "❌" in await say(DONO, "/add https://quebrado.com/p")
        # remover
        assert "Removido" in await say(DONO, "/remove 1")
        assert "Nenhum produto" in await say(DONO, "/list")
        await app.shutdown()

    asyncio.run(rodar())
