"""Escritor de DXF (formato R12/AC1009, ASCII) em Python puro.

R12 abre em praticamente qualquer CAD (AutoCAD, BricsCAD, LibreCAD, ZWCAD...) e não
exige nenhuma biblioteca extra. Entidades: POINT, LINE, POLYLINE (2D/3D) e TEXT.
"""
import math
import re
import unicodedata

_PALETTE = [7, 3, 5, 1, 2, 4, 6, 30, 140, 200]


def layer_name(name):
    """Nome de camada válido em DXF: maiúsculas, dígitos, _ - $ (até 31 caracteres)."""
    ascii_name = unicodedata.normalize("NFKD", str(name)).encode("ascii", "ignore").decode()  # NÍVEL -> NIVEL
    n = re.sub(r"[^A-Za-z0-9_\-$]", "_", ascii_name.upper()).strip("_")
    return (n or "0")[:31]


def _f(v):
    return f"{float(v):.6f}"


class DxfWriter:
    def __init__(self):
        self._layers = {"0": 7}
        self._ents = []
        self.counts = {"POINT": 0, "LINE": 0, "POLYLINE": 0, "TEXT": 0}

    def _layer(self, name):
        n = layer_name(name)
        if n not in self._layers:
            self._layers[n] = _PALETTE[len(self._layers) % len(_PALETTE)]
        return n

    def _add(self, *pairs):
        self._ents.extend(f"{c}\n{v}" for c, v in pairs)

    def point(self, layer, x, y, z=0.0):
        self._add((0, "POINT"), (8, self._layer(layer)), (10, _f(x)), (20, _f(y)), (30, _f(z or 0)))
        self.counts["POINT"] += 1

    def line(self, layer, p1, p2):
        self._add((0, "LINE"), (8, self._layer(layer)),
                  (10, _f(p1[0])), (20, _f(p1[1])), (30, _f(p1[2] if len(p1) > 2 else 0)),
                  (11, _f(p2[0])), (21, _f(p2[1])), (31, _f(p2[2] if len(p2) > 2 else 0)))
        self.counts["LINE"] += 1

    def polyline(self, layer, pts, closed=False):
        """pts: (x, y) ou (x, y, z); z None conta como ausente. 3D se algum z existir."""
        pts = [tuple(p) + (None,) * (3 - len(p)) for p in pts]
        pts = [p for p in pts if all(math.isfinite(c) for c in p[:2])]
        if len(pts) < 2:
            return
        lay = self._layer(layer)
        is3d = any(p[2] is not None and math.isfinite(p[2]) for p in pts)
        flags = (8 if is3d else 0) + (1 if closed else 0)
        self._add((0, "POLYLINE"), (8, lay), (66, 1), (10, "0.0"), (20, "0.0"), (30, "0.0"),
                  (70, flags))
        for x, y, z in pts:
            z = z if (z is not None and math.isfinite(z)) else 0.0
            self._add((0, "VERTEX"), (8, lay), (10, _f(x)), (20, _f(y)), (30, _f(z)),
                      (70, 32 if is3d else 0))
        self._add((0, "SEQEND"), (8, lay))
        self.counts["POLYLINE"] += 1

    def text(self, layer, x, y, z, height, text, rotation=0.0):
        text = str(text).replace("\n", " ").replace("\r", " ")
        if not text:
            return
        self._add((0, "TEXT"), (8, self._layer(layer)), (10, _f(x)), (20, _f(y)),
                  (30, _f(z or 0)), (40, _f(height)), (1, text), (50, _f(rotation)))
        self.counts["TEXT"] += 1

    def to_string(self):
        out = ["0\nSECTION\n2\nHEADER\n9\n$ACADVER\n1\nAC1009\n0\nENDSEC",
               "0\nSECTION\n2\nTABLES",
               "0\nTABLE\n2\nLTYPE\n70\n1\n0\nLTYPE\n2\nCONTINUOUS\n70\n0\n3\nSolid line\n"
               "72\n65\n73\n0\n40\n0.0\n0\nENDTAB",
               "0\nTABLE\n2\nSTYLE\n70\n1\n0\nSTYLE\n2\nSTANDARD\n70\n0\n40\n0.0\n41\n1.0\n"
               "50\n0.0\n71\n0\n42\n0.2\n3\ntxt\n4\n\n0\nENDTAB",
               f"0\nTABLE\n2\nLAYER\n70\n{len(self._layers)}"]
        for name, color in self._layers.items():
            out.append(f"0\nLAYER\n2\n{name}\n70\n0\n62\n{color}\n6\nCONTINUOUS")
        out += ["0\nENDTAB", "0\nENDSEC", "0\nSECTION\n2\nENTITIES"]
        out += self._ents
        out += ["0\nENDSEC", "0\nEOF"]
        return "\n".join(out) + "\n"

    def save(self, path):
        with open(path, "w", encoding="cp1252", errors="replace", newline="\r\n") as fh:
            fh.write(self.to_string())
