"""Leitura e formatação de ângulos (graus/min/seg, decimal, DDD.MMSS)."""
import math
import re

ANGLE_FORMATS = {
    "dms": "Graus, minutos, segundos (123°45'30\")",
    "decimal": "Graus decimais (123,7583)",
    "ddd.mmss": "DDD.MMSS (123.4530)",
}


def norm360(deg):
    return deg % 360.0


def parse_angle(text, fmt="dms"):
    """Texto -> graus decimais. fmt: 'dms', 'decimal' ou 'ddd.mmss'.

    Aceita 123°45'30,5", 123 45 30, 123-45-30, 123:45:30; vírgula ou ponto decimal.
    """
    s = str(text).strip()
    if not s:
        raise ValueError("Ângulo vazio.")
    neg = s[0] == "-"
    s = s.lstrip("+-").strip()

    if fmt == "decimal":
        try:
            v = float(s.replace(",", "."))
        except ValueError:
            raise ValueError(f"Ângulo inválido: {text!r}")
    elif fmt == "ddd.mmss":
        if not re.fullmatch(r"\d+(?:[.,]\d*)?", s):
            raise ValueError(f"Ângulo inválido (DDD.MMSS): {text!r}")
        deg_s, _, frac = s.replace(",", ".").partition(".")
        mm = int(frac[0:2].ljust(2, "0") or 0)
        ss = float(frac[2:4].ljust(2, "0") + ("." + frac[4:] if len(frac) > 4 else ""))
        if mm >= 60 or ss >= 60:
            raise ValueError(f"Minutos/segundos fora do intervalo: {text!r}")
        v = int(deg_s) + mm / 60 + ss / 3600
    else:  # dms
        tokens = re.findall(r"\d+(?:[.,]\d+)?", s)
        if not 1 <= len(tokens) <= 3 or not re.fullmatch(r"[\d.,°'\"′″:\s\-]+", s):
            raise ValueError(f"Ângulo inválido: {text!r}")
        parts = [float(t.replace(",", ".")) for t in tokens] + [0.0, 0.0]
        d, m, sec = parts[:3]
        if m >= 60 or sec >= 60:
            raise ValueError(f"Minutos/segundos fora do intervalo: {text!r}")
        v = d + m / 60 + sec / 3600
    return -v if neg else v


def format_dms(deg, decimals=0):
    """Graus decimais -> 123°45'30" (com arredondamento correto dos segundos)."""
    sign = "-" if deg < 0 else ""
    tot = round(abs(deg) * 3600, decimals)
    d = int(tot // 3600)
    m = int((tot % 3600) // 60)
    s = tot - d * 3600 - m * 60
    width = 2 + (decimals + 1 if decimals else 0)
    return f"{sign}{d}°{m:02d}'{s:0{width}.{decimals}f}\"".replace(".", ",")


def wrap180(deg):
    """Normaliza para (-180, 180]."""
    d = (deg + 180.0) % 360.0 - 180.0
    return 180.0 if d == -180.0 else d


def sec_of(deg):
    return deg * 3600.0


def rad(deg):
    return math.radians(deg)
