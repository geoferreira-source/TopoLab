"""Leitura de arquivos de pontos (CSV/TXT de estação total, GNSS, planilhas exportadas).

Sem dependência do QGIS. Entende separadores ; tab , espaço, decimal com vírgula ou
ponto, separador de milhar, cabeçalho opcional, ordem N/E ou X/Y e acentuação em
UTF-8 ou Windows-1252 (comum em arquivos de estação total no Brasil).
"""
from dataclasses import dataclass, field

import numpy as np

ROLES = {"id": "Ponto / ID", "x": "X (Leste)", "y": "Y (Norte)", "z": "Z (cota)",
         "desc": "Descrição", "skip": "Ignorar"}

# Presets de ordem das colunas. N/E invertido é a fonte clássica de erro: fica explícito.
PRESETS = {
    "Ponto, X (Leste), Y (Norte), Z": ("id", "x", "y", "z"),
    "Ponto, N (Norte), E (Leste), Z": ("id", "y", "x", "z"),
    "Ponto, X, Y, Z, Descrição": ("id", "x", "y", "z", "desc"),
    "Ponto, N, E, Z, Descrição": ("id", "y", "x", "z", "desc"),
    "X (Leste), Y (Norte), Z": ("x", "y", "z"),
    "N (Norte), E (Leste), Z": ("y", "x", "z"),
}


def decode_bytes(raw: bytes):
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return raw.decode(enc), enc
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1", errors="replace"), "latin-1"


def read_text_file(path):
    with open(path, "rb") as fh:
        return decode_bytes(fh.read())


def data_lines(text):
    return [ln for ln in text.splitlines()
            if ln.strip() and not ln.lstrip().startswith(("#", "//", ";;"))]


def split_line(line, delim):
    if delim == " ":
        return line.split()
    return [f.strip().strip('"') for f in line.split(delim)]


def to_float(s, decimal=None):
    """Converte texto em número. decimal: '.', ',' ou None (automático)."""
    s = s.strip().strip('"')
    if not s:
        return None
    if decimal == ",":
        s = s.replace(".", "").replace(",", ".")
    elif decimal == ".":
        s = s.replace(",", "")
    elif "," in s and "." in s:
        s = (s.replace(".", "").replace(",", ".") if s.rfind(",") > s.rfind(".")
             else s.replace(",", ""))
    elif "," in s:
        s = s.replace(",", ".")
    try:
        v = float(s)
    except ValueError:
        return None
    return v if np.isfinite(v) else None


def guess_delimiter(lines):
    best = None
    sample = lines[:30]
    for prio, d in enumerate((";", "\t", ",", " ")):
        rows = [split_line(ln, d) for ln in sample]
        cols = [len(r) for r in rows]
        mode = max(set(cols), key=cols.count)
        if mode < 2:
            continue
        consistency = cols.count(mode) / len(cols)
        if consistency < 0.8:
            continue
        dec = "." if d == "," else None
        fields = [f for r in rows for f in r]
        numeric = sum(to_float(f, dec) is not None for f in fields) / len(fields)
        score = (round(consistency, 2), round(numeric, 2), -prio)
        if best is None or score > best[0]:
            best = (score, d)
    return best[1] if best else None


def guess_decimal(lines, delim):
    if delim == ",":
        return "."
    comma = dot = 0
    for ln in lines[:50]:
        for f in split_line(ln, delim):
            if f.replace(",", "", 1).lstrip("-").isdigit() and "," in f:
                comma += 1
            elif f.replace(".", "", 1).lstrip("-").isdigit() and "." in f:
                dot += 1
    return "," if comma > dot else "."


def preview_rows(text, delimiter=None, n=15):
    """(delimitador usado, primeiras n linhas separadas em colunas)."""
    lines = data_lines(text)
    delim = delimiter or guess_delimiter(lines) or ";"
    return delim, [split_line(ln, delim) for ln in lines[:n]]


@dataclass
class ParseResult:
    ids: list
    xyz: np.ndarray                 # (n, 3)
    desc: list
    n_skipped: int
    skipped: list = field(default_factory=list)  # (nº da linha de dados, texto) das primeiras
    delimiter: str = ";"
    decimal: str = "."
    header: bool = False


def parse_points(text, roles, delimiter=None, decimal=None, header=None):
    """Converte o texto em pontos.

    roles: papel de cada coluna ('id','x','y','z','desc','skip'); X, Y e Z obrigatórios.
    delimiter/decimal/header: None = detectar automaticamente.
    """
    roles = list(roles)
    for r in ("x", "y", "z"):
        if r not in roles:
            raise ValueError("Defina as colunas X, Y e Z.")
    lines = data_lines(text)
    if not lines:
        raise ValueError("O arquivo está vazio.")
    delim = delimiter or guess_delimiter(lines)
    if delim is None:
        raise ValueError("Não foi possível detectar o separador de colunas.")
    dec = decimal or guess_decimal(lines, delim)
    ix, iy, iz = roles.index("x"), roles.index("y"), roles.index("z")
    need = max(ix, iy, iz)

    if header is None:  # primeira linha é cabeçalho se algum de X/Y/Z não é número
        first = split_line(lines[0], delim)
        header = len(first) > need and any(to_float(first[i], dec) is None for i in (ix, iy, iz))
    start = 1 if header else 0

    iid = roles.index("id") if "id" in roles else None
    idesc = roles.index("desc") if "desc" in roles else None
    ids, xyz, desc, skipped, n_skip = [], [], [], [], 0
    for k, line in enumerate(lines[start:], start + 1):
        f = split_line(line, delim)
        vals = None
        if len(f) > need:
            x, y, z = to_float(f[ix], dec), to_float(f[iy], dec), to_float(f[iz], dec)
            if None not in (x, y, z):
                vals = (x, y, z)
        if vals is None:
            n_skip += 1
            if len(skipped) < 20:
                skipped.append((k, line.strip()))
            continue
        xyz.append(vals)
        ids.append(f[iid] if iid is not None and iid < len(f) else str(len(ids) + 1))
        if idesc is not None and idesc < len(f):
            last = idesc == len(roles) - 1
            desc.append(" ".join(f[idesc:]) if (delim == " " and last) else f[idesc])
        else:
            desc.append("")
    if not xyz:
        raise ValueError("Nenhuma linha válida. Confira separador, decimal e colunas.")
    return ParseResult(ids, np.array(xyz, dtype=float), desc, n_skip, skipped, delim, dec,
                       bool(header))
