"""Leitura de DXF (ASCII) para topografia, em Python puro.

Entende as entidades que costumam vir de levantamentos e projetos:
POINT, CIRCLE e INSERT (blocos, com atributos) como pontos; TEXT e MTEXT (cotas e nomes
escritos ao lado dos pontos); LINE, LWPOLYLINE e POLYLINE 2D/3D como linhas. Só o espaço
do modelo é lido (o papel, não). Arcos de polilinha (bulge) viram retas entre os
vértices; SPLINE, HATCH, 3DFACE e outras são contadas como não suportadas.
"""
import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field

import numpy as np

POINT_KINDS = ("POINT", "INSERT", "CIRCLE")
TEXT_KINDS = ("TEXT", "MTEXT")
LINE_KINDS = ("LINE", "LWPOLYLINE", "POLYLINE")

# atributos de bloco reconhecidos (comparação sem maiúsculas)
ID_TAGS = ("PT", "PONTO", "NUM", "NUMERO", "N", "ID", "NOME", "PTO", "POINT", "NAME")
Z_TAGS = ("COTA", "ELEV", "ELEVACAO", "Z", "ALT", "ALTITUDE", "H", "ELEVATION")
DESC_TAGS = ("DESC", "DESCRICAO", "COD", "CODIGO", "OBS", "CODE", "DESCRIPTION")

_NUM_TEXT = re.compile(r"^\s*(?:[A-Za-z]{1,6}\.?\s*[=:]?\s*)?([-+]?\d{1,6}[.,]\d+)\s*m?\s*$")
_MTEXT_CODES = re.compile(r"\\[ACcFfHhLlOoQqTtWwKkSs][^;\\{}]*;?|\\[Pp~]|[{}]")


@dataclass
class DxfEntity:
    kind: str                 # POINT, INSERT, CIRCLE, TEXT, MTEXT, LINE, LWPOLYLINE, POLYLINE
    layer: str
    xyz: np.ndarray           # (k, 3); pontos e textos têm k = 1
    closed: bool = False
    text: str = ""
    block: str = ""
    attribs: dict = field(default_factory=dict)


@dataclass
class DxfDrawing:
    entities: list
    unsupported: Counter
    encoding: str

    def layers(self):
        """{camada: Counter de tipos} na ordem em que aparecem."""
        out = {}
        for e in self.entities:
            out.setdefault(e.layer, Counter())[e.kind] += 1
        return out


def _decode(raw):
    for enc in ("utf-8", "cp1252"):
        try:
            return raw.decode(enc), enc
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1"), "latin-1"


def _unicode_escapes(s):
    return re.sub(r"\\U\+([0-9A-Fa-f]{4})", lambda m: chr(int(m.group(1), 16)), s)


def clean_mtext(s):
    s = _MTEXT_CODES.sub(lambda m: " " if m.group(0) in ("\\P", "\\p", "\\~") else "", s)
    return re.sub(r"\s+", " ", s).strip()


def number_in_text(s):
    """Cota escrita num texto ("123,45", "C=123.450", "123,45 m"); None se não for número.

    Exige parte decimal: números inteiros costumam ser o número do ponto, não a cota.
    """
    m = _NUM_TEXT.match(s or "")
    return float(m.group(1).replace(",", ".")) if m else None


def _pairs(text):
    lines = text.splitlines()
    if len(lines) < 2:
        raise ValueError("Arquivo DXF vazio.")
    for i in range(0, len(lines) - 1, 2):
        code = lines[i].strip()
        try:
            yield int(code), lines[i + 1].strip()
        except ValueError:
            raise ValueError("Não parece um DXF em texto (ASCII). DXF binário não é suportado: "
                             "salve como DXF ASCII no CAD.")


class _Rec:
    """Grupos (código, valor) de uma entidade."""

    def __init__(self, kind):
        self.kind, self.items = kind, []

    def get(self, code, default=None):
        for c, v in self.items:
            if c == code:
                return v
        return default

    def num(self, code, default=0.0):
        v = self.get(code)
        try:
            return float(v) if v is not None else default
        except ValueError:
            return default

    def all(self, code):
        return [v for c, v in self.items if c == code]


def _records(text):
    """Entidades da seção ENTITIES, como _Rec, na ordem do arquivo."""
    section, rec, out = None, None, []
    expect_name = False
    for code, value in _pairs(text):
        if code == 0:
            if rec is not None and section == "ENTITIES":
                out.append(rec)
            rec = None
            if value == "SECTION":
                expect_name = True
                continue
            if value == "ENDSEC":
                section = None
                continue
            if section == "ENTITIES":
                rec = _Rec(value)
            continue
        if expect_name and code == 2:
            section, expect_name = value, False
            continue
        if rec is not None:
            rec.items.append((code, value))
    if rec is not None and section == "ENTITIES":
        out.append(rec)
    return out


def _ocs_x(rec, x):
    # extrusão (0, 0, -1): sistema espelhado em X (comum em CAD); outras são raras em topografia
    return -x if rec.num(230, 1.0) < 0 else x


def _pt(rec, cx=10):
    return np.array([[_ocs_x(rec, rec.num(cx)), rec.num(cx + 10), rec.num(cx + 20)]])


def read_dxf(source):
    """Lê um DXF (caminho ou bytes/str) e devolve um DxfDrawing."""
    if isinstance(source, (bytes, bytearray)):
        text, enc = _decode(bytes(source))
    elif isinstance(source, str) and "\n" in source:
        text, enc = source, "texto"
    else:
        with open(source, "rb") as fh:
            text, enc = _decode(fh.read())
    recs = _records(text)
    ents, unsupported = [], Counter()
    i = 0
    while i < len(recs):
        r = recs[i]
        i += 1
        if r.get(67) == "1":     # espaço do papel
            if r.kind in ("POLYLINE", "INSERT"):
                while i < len(recs) and recs[i].kind != "SEQEND":
                    i += 1
                i += 1
            continue
        layer = r.get(8, "0")
        k = r.kind
        if k == "POINT":
            ents.append(DxfEntity(k, layer, _pt(r)))
        elif k == "CIRCLE":
            ents.append(DxfEntity(k, layer, _pt(r)))
        elif k == "INSERT":
            attribs = {}
            if r.get(66) == "1":
                while i < len(recs) and recs[i].kind != "SEQEND":
                    a = recs[i]
                    if a.kind == "ATTRIB":
                        attribs[(a.get(2) or "").strip().upper()] = _unicode_escapes(a.get(1, "")).strip()
                    i += 1
                i += 1
            ents.append(DxfEntity(k, layer, _pt(r), block=r.get(2, ""), attribs=attribs))
        elif k in ("TEXT", "MTEXT"):
            if k == "TEXT":
                aligned = (r.get(72, "0") not in ("0", None)) or (r.get(73, "0") not in ("0", None))
                xyz = _pt(r, 11) if aligned and r.get(11) is not None else _pt(r)
                txt = _unicode_escapes(r.get(1, ""))
            else:
                xyz = _pt(r)
                txt = clean_mtext(_unicode_escapes("".join(r.all(3)) + r.get(1, "")))
            ents.append(DxfEntity(k, layer, xyz, text=txt.strip()))
        elif k == "LINE":
            xyz = np.vstack([_pt(r, 10), _pt(r, 11)])
            ents.append(DxfEntity(k, layer, xyz))
        elif k == "LWPOLYLINE":
            xs = [float(v) for v in r.all(10)]
            ys = [float(v) for v in r.all(20)]
            n = min(len(xs), len(ys))
            if n >= 2:
                z = r.num(38)
                xyz = np.column_stack([[_ocs_x(r, x) for x in xs[:n]], ys[:n], np.full(n, z)])
                ents.append(DxfEntity(k, layer, xyz, closed=bool(int(r.num(70)) & 1)))
        elif k == "POLYLINE":
            flags = int(r.num(70))
            elev = r.num(30)
            verts = []
            while i < len(recs) and recs[i].kind != "SEQEND":
                v = recs[i]
                if v.kind == "VERTEX" and not (int(v.num(70)) & 128 and not int(v.num(70)) & 64):
                    z = v.num(30) if flags & 8 else elev
                    verts.append((_ocs_x(r, v.num(10)), v.num(20), z))
                i += 1
            i += 1
            if flags & (16 | 64):
                unsupported["POLYLINE (malha)"] += 1
            elif len(verts) >= 2:
                ents.append(DxfEntity(k, layer, np.array(verts, float), closed=bool(flags & 1)))
        elif k in ("SEQEND", "VERTEX", "ATTRIB"):
            continue
        else:
            unsupported[k] += 1
    return DxfDrawing(ents, unsupported, enc)


# --- montagem dos dados de topografia ---------------------------------------------------
@dataclass
class DxfSurvey:
    points: list = field(default_factory=list)   # (id, x, y, z, desc, camada, origem)
    lines: list = field(default_factory=list)    # (camada, xyz (k, 3), fechada)
    polygons: list = field(default_factory=list)  # (camada, xy (k, 2)) anéis fechados
    stats: dict = field(default_factory=dict)


def _tag(attribs, tags):
    for t in tags:
        if t in attribs and attribs[t] != "":
            return attribs[t]
    return None


def guess_roles(drawing):
    """Papel sugerido para cada camada: 'pontos', 'cotas', 'linhas', 'limite' ou 'ignorar'."""
    roles = {}
    for layer, cnt in drawing.layers().items():
        name = layer.upper()
        n_pts = sum(cnt[k] for k in POINT_KINDS)
        n_txt = sum(cnt[k] for k in TEXT_KINDS)
        n_lin = sum(cnt[k] for k in LINE_KINDS)
        ents = [e for e in drawing.entities if e.layer == layer]
        numeric = sum(1 for e in ents if e.kind in TEXT_KINDS and number_in_text(e.text) is not None)
        if any(w in name for w in ("LIMIT", "PERIM", "DIVISA", "CONTORNO", "POLIGONAL")) and n_lin:
            roles[layer] = "limite"
        elif n_pts >= max(n_txt, n_lin) and n_pts:
            roles[layer] = "pontos"
        elif n_txt and numeric >= 0.6 * n_txt and numeric >= n_lin:
            roles[layer] = "cotas"
        elif n_lin:
            roles[layer] = "linhas"
        else:
            roles[layer] = "ignorar"
    return roles


def build_survey(drawing, roles, text_radius=2.0, texts_as_points=True, line_vertices_as_points=False):
    """Pontos cotados, linhas e polígonos a partir dos papéis das camadas.

    roles: {camada: 'pontos' | 'cotas' | 'linhas' | 'limite' | 'ignorar'}.
    Pontos sem cota (Z = 0) pegam a cota do texto numérico mais próximo (camadas 'cotas')
    dentro de `text_radius`; cada texto serve a um ponto só. Textos de cota que sobram
    viram pontos se `texts_as_points`. Linhas com cota podem ceder os vértices como pontos.
    """
    from scipy.spatial import cKDTree
    sv = DxfSurvey()
    role = lambda e: roles.get(e.layer, "ignorar")  # noqa: E731
    texts = [e for e in drawing.entities if role(e) == "cotas" and e.kind in TEXT_KINDS]
    tvals = [number_in_text(e.text) for e in texts]
    tnum = [(e, v) for e, v in zip(texts, tvals) if v is not None]
    used = set()
    tree = cKDTree(np.array([e.xyz[0, :2] for e, _ in tnum])) if tnum else None

    from_text = from_attr = from_geom = 0
    pts = [e for e in drawing.entities if role(e) == "pontos" and e.kind in POINT_KINDS]
    for k, e in enumerate(pts):
        x, y, z = map(float, e.xyz[0])
        pid = _tag(e.attribs, ID_TAGS) or ""
        desc = _tag(e.attribs, DESC_TAGS) or (e.block if e.kind == "INSERT" else "")
        za = _tag(e.attribs, Z_TAGS)
        za = number_in_text(za) if za is not None else None
        if za is None and _tag(e.attribs, Z_TAGS) is not None:
            try:
                za = float(_tag(e.attribs, Z_TAGS).replace(",", "."))
            except ValueError:
                za = None
        src = "geometria"
        if za is not None:
            z, src = za, "atributo"
            from_attr += 1
        elif (z == 0 or not math.isfinite(z)) and tree is not None:
            cand = tree.query_ball_point((x, y), text_radius)
            cand = [c for c in cand if c not in used]
            if cand:
                c = min(cand, key=lambda c: math.hypot(*(tnum[c][0].xyz[0, :2] - (x, y))))
                used.add(c)
                z, src = tnum[c][1], "texto"
                from_text += 1
            else:
                z = float("nan")
        else:
            from_geom += 1
        sv.points.append((pid or f"{k + 1}", x, y, z, desc, e.layer, src))
    leftover = 0
    if texts_as_points:
        for c, (e, v) in enumerate(tnum):
            if c not in used:
                x, y = map(float, e.xyz[0, :2])
                sv.points.append((f"T{c + 1}", x, y, v, "", e.layer, "texto (sem ponto)"))
                leftover += 1
    for e in drawing.entities:
        r = role(e)
        if e.kind not in LINE_KINDS or r not in ("linhas", "limite"):
            continue
        xyz = e.xyz
        if e.closed and len(xyz) >= 3 and not np.allclose(xyz[0, :2], xyz[-1, :2]):
            xyz = np.vstack([xyz, xyz[:1]])
        closed = e.closed or (len(xyz) >= 4 and np.array_equal(xyz[0, :2], xyz[-1, :2]))
        if r == "limite":
            if closed and len(xyz) >= 4:
                sv.polygons.append((e.layer, xyz[:, :2]))
            else:
                sv.lines.append((e.layer, xyz, closed))
        else:
            sv.lines.append((e.layer, xyz, closed))
            if line_vertices_as_points and np.isfinite(xyz[:, 2]).all() and np.any(xyz[:, 2] != 0):
                for j, (x, y, z) in enumerate(xyz[:-1] if closed else xyz):
                    sv.points.append((f"L{len(sv.points) + 1}", float(x), float(y), float(z), "",
                                      e.layer, "vértice de linha"))
    no_z = sum(1 for p in sv.points if not math.isfinite(p[3]))
    sv.stats = {"pontos": len(sv.points), "cota_texto": from_text, "cota_atributo": from_attr,
                "cota_geometria": from_geom, "textos_sem_ponto": leftover, "sem_cota": no_z,
                "linhas": len(sv.lines), "poligonos": len(sv.polygons),
                "nao_suportadas": dict(drawing.unsupported)}
    return sv


def describe_layer(counter):
    names = {"POINT": "ponto", "INSERT": "bloco", "CIRCLE": "círculo", "TEXT": "texto",
             "MTEXT": "texto", "LINE": "linha", "LWPOLYLINE": "polilinha", "POLYLINE": "polilinha"}
    agg = defaultdict(int)
    for k, n in counter.items():
        agg[names.get(k, k.lower())] += n
    return ", ".join(f"{n} {k}{'s' if n > 1 and not k.endswith('s') else ''}" for k, n in agg.items())
