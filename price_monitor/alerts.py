from .prices import brl


def evaluate(price, target, prev_price, last_notified, drop_pct=5.0):
    """Decide se avisa. Retorna (motivo|None, novo last_notified).

    Avisa quando atinge o alvo ou cai >= drop_pct% vs. a leitura anterior, mas só se
    o preço for menor que o último avisado (sem spam); se o preço sobe, o aviso rearma.
    """
    if last_notified is not None and price > last_notified:
        last_notified = None
    reason = None
    if target is not None and price <= target:
        reason = "target"
    elif prev_price and price <= prev_price * (1 - drop_pct / 100):
        reason = "drop"
    if reason and (last_notified is None or price < last_notified):
        return reason, price
    return None, last_notified


def format_alert(p, price, reason) -> str:
    prev = p["last_price"]
    why = (
        f"atingiu seu alvo de {brl(p['target'])}"
        if reason == "target"
        else f"queda de {(1 - price / prev) * 100:.0f}%"
    )
    before = f" (antes {brl(prev)})" if prev and prev != price else ""
    return f"🔔 {p['title']}\n{brl(price)}{before}: {why}\n{p['url']}"


async def check_product(db, fetch_item, notify, p, drop_pct=5.0) -> float | None:
    """Lê o preço de um produto, grava e avisa se for o caso. None se a leitura falhou."""
    try:
        item = await fetch_item(p["url"], p["selector"])
    except Exception as e:  # fronteira: qualquer falha de loja/parsing não derruba o ciclo
        if db.record_failure(p["id"]) == 3:
            await notify(p["chat_id"], f"⚠️ Não consegui ler o preço de {p['title']} 3 vezes seguidas: {e}")
        return None
    reason, notified = evaluate(item.price, p["target"], p["last_price"], p["last_notified"], drop_pct)
    db.record_price(p["id"], item.price, notified)
    if reason:
        await notify(p["chat_id"], format_alert(p, item.price, reason))
    return item.price
