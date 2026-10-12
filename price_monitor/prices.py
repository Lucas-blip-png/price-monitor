import re
from typing import NamedTuple


class Item(NamedTuple):
    title: str
    price: float


_BRL = re.compile(r"R\$\s*(\d{1,3}(?:\.\d{3})+(?:,\d{2})?|\d+(?:,\d{2})?)")
_MILHAR = re.compile(r"\d{1,3}(\.\d{3})+")


def parse_price(text) -> float | None:
    """'R$ 1.234,56' -> 1234.56; '1299.90' -> 1299.9; '2.499' -> 2499.0."""
    s = re.sub(r"[^\d.,]", "", str(text))
    if not s:
        return None
    if "," in s:  # BR: ponto = milhar, vírgula = decimal
        s = s.replace(".", "").replace(",", ".")
    elif _MILHAR.fullmatch(s):
        s = s.replace(".", "")
    try:
        return float(s)
    except ValueError:
        return None


def find_prices(text: str) -> list[float]:
    """Todos os 'R$ ...' de um texto livre (posts de promoção)."""
    return [p for m in _BRL.findall(text) if (p := parse_price(m)) is not None]


def brl(v: float) -> str:
    return "R$ " + f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
