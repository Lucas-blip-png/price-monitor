import logging
import os
import re
import time
from pathlib import Path

from telegram import LinkPreviewOptions, Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler, filters

from . import promos
from .alerts import check_product
from .db import DB
from .http import FetchError
from .prices import brl, parse_price
from .stores import fetch_item

log = logging.getLogger("price_monitor")
URL = re.compile(r"https?://\S+")
NAME = re.compile(r"\w{4,32}")  # entra na URL t.me/s/<canal>, então é validado

HELP = """Monitor de preços 🛒
Cole um link de produto (ou /add <url> [alvo] [css=<seletor>]) e eu aviso quando o preço cair.

/list · /remove <id> · /target <id> <valor> · /history <id> · /check
/canal add|remove|list <@canal>  (canais públicos de promoção)
/palavra add|remove|list <termo>  (avisa posts com essa palavra)
/melhor <produto>  (as ofertas mais baratas dos canais e dos seus produtos)"""


def notifier(bot):
    async def send(chat_id, text):
        await bot.send_message(chat_id, text, link_preview_options=LinkPreviewOptions(is_disabled=True))

    return send


async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(HELP)


async def add(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text, chat = update.message.text, update.effective_chat.id
    if not (m := URL.search(text)):
        return await update.message.reply_text("Uso: /add <url> [preço alvo] [css=<seletor>]")
    url, css = m[0], re.search(r"\bcss=(.+)$", text, re.S)
    selector = css[1].strip() if css else None
    nums = re.findall(r"\d[\d.,]*", (text[: css.start()] if css else text).replace(url, ""))
    target = parse_price(nums[0]) if nums else None
    await update.message.reply_text("🔎 Lendo o preço…")
    try:
        item = await fetch_item(url, selector)
    except Exception as e:  # fronteira com sites externos
        return await update.message.reply_text(f"❌ Não consegui ler o preço: {e}")
    pid = ctx.bot_data["db"].add_product(chat, url, item.title, item.price, target, selector)
    alvo = f" · alvo {brl(target)}" if target else ""
    await update.message.reply_text(f"✅ #{pid} {item.title}\nAgora: {brl(item.price)}{alvo}")


async def list_(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    rows = ctx.bot_data["db"].products(update.effective_chat.id)
    lines = [
        f"#{p['id']} {p['title'][:60]}\n   {brl(p['last_price'])}" + (f" · alvo {brl(p['target'])}" if p["target"] else "")
        for p in rows
    ]
    await update.message.reply_text("\n".join(lines) or "Nenhum produto. Cole um link para começar.")


def _id(ctx, n=1):
    s = ctx.args[0].lstrip("#") if len(ctx.args) >= n else ""  # aceita "#1" como o /list mostra
    return int(s) if s.isdigit() else None


async def remove(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    pid = _id(ctx)
    ok = pid and ctx.bot_data["db"].remove_product(pid, update.effective_chat.id)
    await update.message.reply_text("🗑️ Removido." if ok else "Uso: /remove <id> (veja /list)")


async def target(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    pid, val = _id(ctx, 2), parse_price(ctx.args[1]) if len(ctx.args) > 1 else None
    ok = pid and val and ctx.bot_data["db"].set_target(pid, update.effective_chat.id, val)
    await update.message.reply_text(f"🎯 Alvo: {brl(val)}" if ok else "Uso: /target <id> <valor>")


async def history(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    db, pid = ctx.bot_data["db"], _id(ctx)
    p = pid and db.product(pid, update.effective_chat.id)
    if not p:
        return await update.message.reply_text("Uso: /history <id> (veja /list)")
    rows = db.history(pid)
    prices = [r["price"] for r in rows]
    last = "\n".join(f"  {time.strftime('%d/%m %H:%M', time.localtime(r['ts']))}  {brl(r['price'])}" for r in rows[-5:])
    await update.message.reply_text(
        f"{p['title'][:60]}\natual {brl(prices[-1])} · mín {brl(min(prices))} · máx {brl(max(prices))}\nÚltimas mudanças:\n{last}"
    )


async def check(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    db, send, lines = ctx.bot_data["db"], notifier(ctx.bot), []
    for p in db.products(update.effective_chat.id):
        price = await check_product(db, fetch_item, send, p, ctx.bot_data["drop_pct"])
        lines.append(f"#{p['id']} {brl(price)}" if price is not None else f"#{p['id']} ❌ falhou")
    await update.message.reply_text("\n".join(lines) or "Nenhum produto.")


async def canal(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    db, chat, a = ctx.bot_data["db"], update.effective_chat.id, ctx.args
    sub = a[0].lower() if a else "list"
    name = a[1].lstrip("@").lower() if len(a) > 1 else ""
    if sub == "list":
        msg = "\n".join(f"@{c['name']}" for c in db.channels(chat)) or "Nenhum canal."
    elif sub == "add" and NAME.fullmatch(name):
        try:
            posts = await promos.fetch_channel(name)
        except FetchError as e:
            return await update.message.reply_text(f"❌ {e}")
        if not posts:
            return await update.message.reply_text("❌ Canal não encontrado ou sem preview público (t.me/s/…).")
        db.add_channel(chat, name, max(p.id for p in posts))  # só posts novos a partir de agora
        promos.remember(db, chat, name, posts)  # mas os recentes já alimentam o /melhor
        msg = f"✅ Monitorando @{name}. Use /palavra add <termo> para filtrar e /melhor <produto> para comparar."
    elif sub == "remove" and name:
        msg = "🗑️ Removido." if db.remove_channel(chat, name) else "Canal não está na lista."
    else:
        msg = "Uso: /canal add|remove|list <@canal>"
    await update.message.reply_text(msg)


async def palavra(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    db, chat, a = ctx.bot_data["db"], update.effective_chat.id, ctx.args
    sub, term = (a[0].lower() if a else "list"), " ".join(a[1:]).strip()
    if sub == "list":
        msg = "\n".join(db.keywords(chat)) or "Nenhuma palavra."
    elif sub == "add" and term:
        db.add_keyword(chat, term)
        msg = f"✅ «{term}» adicionada."
    elif sub == "remove" and term:
        msg = "🗑️ Removida." if db.remove_keyword(chat, term) else "Palavra não está na lista."
    else:
        msg = "Uso: /palavra add|remove|list <termo>"
    await update.message.reply_text(msg)


def _ago(ts: float) -> str:
    s = time.time() - ts
    return "agora" if s < 3600 else f"{int(s // 3600)}h" if s < 86400 else f"{int(s // 86400)}d"


async def melhor(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    term = " ".join(ctx.args).strip()
    reply = lambda t: update.message.reply_text(t, link_preview_options=LinkPreviewOptions(is_disabled=True))
    if not term:
        return await reply("Uso: /melhor <produto>, por exemplo /melhor rtx 4060")
    deals = promos.best_deals(ctx.bot_data["db"], update.effective_chat.id, term)
    if not deals:
        return await reply("Nada encontrado nos canais salvos nem nos seus produtos. Adicione canais com /canal add.")
    lines = [f"🏆 Melhores preços para «{term}»"]
    lines += [f"{i}. {brl(d.price)} · {d.source} · {_ago(d.ts)}\n   {d.link}" for i, d in enumerate(deals, 1)]
    await reply("\n".join(lines))


async def job_prices(ctx: ContextTypes.DEFAULT_TYPE):
    db, send = ctx.bot_data["db"], notifier(ctx.bot)
    for p in db.products():
        await check_product(db, fetch_item, send, p, ctx.bot_data["drop_pct"])


async def job_promos(ctx: ContextTypes.DEFAULT_TYPE):
    await promos.scan(ctx.bot_data["db"], notifier(ctx.bot))


async def deny(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Chat fora da lista: não responde, mas registra o ID para o dono poder autorizá-lo."""
    u = update.effective_user
    log.warning("chat não autorizado: id=%s usuário=@%s", update.effective_chat.id, u.username if u else None)


async def on_error(update, ctx: ContextTypes.DEFAULT_TYPE):
    log.error("erro no handler", exc_info=ctx.error)


def load_env(path=".env"):
    if Path(path).exists():
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip("\"'"))


def need(name):
    if not (v := os.getenv(name)):
        raise SystemExit(f"Defina {name} (veja .env.example)")
    return v


def build_app(builder, allowed, db_path, drop_pct=5.0):
    """Monta handlers e jobs. `builder` já traz token (ou um bot falso, nos testes)."""
    app = builder.concurrent_updates(True).build()
    app.bot_data.update(db=DB(db_path), drop_pct=drop_pct)
    ok = filters.Chat(chat_id=allowed)  # só os chats autorizados falam com o bot
    for names, fn in (
        (["start", "help", "ajuda"], start),
        (["add"], add),
        (["list", "lista"], list_),
        (["remove", "remover"], remove),
        (["target"], target),
        (["history"], history),
        (["check"], check),
        (["canal"], canal),
        (["palavra"], palavra),
        (["melhor"], melhor),
    ):
        app.add_handler(CommandHandler(names, fn, filters=ok))
    app.add_handler(MessageHandler(ok & filters.TEXT & ~filters.COMMAND & filters.Regex(URL), add))
    app.add_handler(MessageHandler(~ok, deny), group=1)
    app.add_error_handler(on_error)
    if app.job_queue:
        app.job_queue.run_repeating(job_prices, interval=int(os.getenv("CHECK_INTERVAL_MIN", "30")) * 60, first=30)
        app.job_queue.run_repeating(job_promos, interval=int(os.getenv("PROMO_INTERVAL_MIN", "10")) * 60, first=60)
    return app


def main():
    logging.basicConfig(format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=logging.INFO)
    logging.getLogger("httpx").setLevel(logging.WARNING)  # o INFO do httpx imprime a URL com o token do bot
    load_env()
    token, allowed = need("TELEGRAM_TOKEN"), [int(x) for x in need("ALLOWED_CHAT_IDS").split(",")]
    db_path = os.getenv("DB_PATH", "data/price_monitor.db")
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    build_app(ApplicationBuilder().token(token), allowed, db_path, float(os.getenv("DROP_PCT", "5"))).run_polling()


if __name__ == "__main__":
    main()
