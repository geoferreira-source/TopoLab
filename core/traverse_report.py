"""Relatório HTML, memorial descritivo e CSV de poligonais."""
import csv
import html
from datetime import datetime

import numpy as np

from .report_html import fmt
from .traverse import METHODS, TraverseResult, traverse_rows


def _verdict(ok, flag_defined):
    if not flag_defined:
        return "sem tolerância definida"
    return '<span style="color:#2f5d3a">dentro da tolerância</span>' if ok else \
        '<span style="color:#c0392b"><b>fora da tolerância</b></span>'


def traverse_report_html(res: TraverseResult, title="Poligonal", params=()):
    esc = html.escape
    rows = traverse_rows(res)
    lev = res.z is not None

    def cells(r):
        c = [esc(str(r["estacao"])), r["angulo"], r["angulo_ajustado"], r["azimute"],
             "" if r["distancia"] is None else fmt(r["distancia"], 3),
             "" if r["dE"] is None else fmt(r["dE"], 3),
             "" if r["dN"] is None else fmt(r["dN"], 3),
             fmt(r["x"], 3), fmt(r["y"], 3)]
        if lev:
            c += ["" if r["dv"] is None else fmt(r["dv"], 3), fmt(r["z"], 3)]
        return c
    body = "".join("<tr>" + "".join(f"<td class='n'>{c}</td>" for c in cells(r)) + "</tr>" for r in rows)
    inputs = "".join(f"<tr><td>{esc(str(k))}</td><td>{esc(str(v))}</td></tr>" for k, v in params)
    ang_tol = res.ang_tol_sec
    tol_txt = "" if np.isnan(ang_tol) else f' (tolerância {fmt(ang_tol, 1)}")'
    prec_min = "" if np.isnan(res.min_precision) else f" (mínimo 1:{fmt(res.min_precision, 0)})"
    prec = "∞" if np.isinf(res.rel_precision) else f"1:{fmt(res.rel_precision, 0)}"
    area = ("" if np.isnan(res.area) else
            f"<tr><td>Área</td><td>{fmt(res.area, 3)} m² &nbsp;({fmt(res.area / 10000, 4)} ha)</td></tr>")
    closure = "" if res.mode == "aberta" else f"""
<tr><td>Erro angular de fechamento</td><td>{fmt(res.ang_error_sec, 1)}"{tol_txt} &mdash; {_verdict(res.angular_ok, not np.isnan(ang_tol))}</td></tr>
<tr><td>Erro linear (E, N, total)</td><td>{fmt(res.err_E, 4)} ; {fmt(res.err_N, 4)} ; {fmt(res.lin_error, 4)} m</td></tr>
<tr><td>Precisão relativa</td><td>{prec}{prec_min} &mdash; {_verdict(res.linear_ok, not np.isnan(res.min_precision))}</td></tr>"""
    if lev and res.mode != "aberta":
        vt = "" if np.isnan(res.v_tol) else f" (tolerância {fmt(res.v_tol, 4)} m)"
        closure += (f"<tr><td>Erro altimétrico de fechamento</td><td>{fmt(res.v_error, 4)} m{vt} &mdash; "
                    f"{_verdict(res.vertical_ok, not np.isnan(res.v_tol))}</td></tr>")
    if lev:
        closure += ("<tr><td>Nivelamento</td><td>trigonométrico (distância inclinada e ângulo zenital)"
                    + ("; com correção de curvatura e refração (k = 0,13)" if res.curvature else
                       "; sem correção de curvatura e refração") + "</td></tr>")
    return f"""<!DOCTYPE html><html lang="pt-BR"><head><meta charset="utf-8"><title>{esc(title)}</title>
<style>body{{font-family:Arial,Helvetica,sans-serif;margin:24px;color:#222}}
h2{{color:#2f5d3a;margin-bottom:4px}} small{{color:#666}}
table{{border-collapse:collapse;margin:10px 0}} td,th{{border:1px solid #ccc;padding:5px 10px;text-align:left}}
th{{background:#eef3ea}} td.n{{text-align:right}}</style></head><body>
<h2>{esc(title)}</h2><small>Gerado em {datetime.now().strftime('%d/%m/%Y %H:%M')} pelo TopoLab</small>
<h3>Dados de entrada</h3><table>{inputs}</table>
<h3>Resumo</h3><table>
<tr><td>Modo</td><td>{esc(res.mode)}</td></tr>
<tr><td>Ajuste linear</td><td>{esc(METHODS[res.method])}</td></tr>
<tr><td>Perímetro / comprimento</td><td>{fmt(res.perimeter, 3)} m</td></tr>{closure}{area}
</table>
<h3>Caderneta calculada</h3>
<table><tr><th>Estação</th><th>Ângulo medido</th><th>Ângulo ajustado</th><th>Azimute</th>
<th>Distância horiz. (m)</th><th>&Delta;E ajust.</th><th>&Delta;N ajust.</th><th>X / Leste</th><th>Y / Norte</th>{"<th>&Delta;V ajust.</th><th>Cota</th>" if lev else ""}</tr>{body}</table>
<p><small>Azimutes a partir do Norte, sentido horário. Unidades do CRS. Confira os resultados antes de uso profissional.</small></p>
</body></html>"""


def memorial_text(res: TraverseResult, title="Memorial descritivo", crs_text="", decimals=2):
    """Texto-base do memorial (rascunho). Azimutes e distâncias saem das coordenadas
    ajustadas, para o texto ser coerente com os vértices listados."""
    from .route import memorial_from_coords
    return memorial_from_coords(res.names, res.x, res.y, res.mode == "fechada", title,
                                crs_text, decimals)


def write_traverse_csv(path, res: TraverseResult, decimal=","):
    def n(v, d=3):
        return "" if v is None else f"{v:.{d}f}".replace(".", decimal)
    with open(path, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh, delimiter=";")
        lev = res.z is not None
        w.writerow(["ESTACAO", "ANGULO_MEDIDO", "ANGULO_AJUSTADO", "AZIMUTE", "DISTANCIA",
                    "DELTA_E", "DELTA_N", "X", "Y"] + (["DELTA_V", "COTA"] if lev else []))
        for r in traverse_rows(res):
            w.writerow([r["estacao"], r["angulo"], r["angulo_ajustado"], r["azimute"],
                        n(r["distancia"]), n(r["dE"], 4), n(r["dN"], 4), n(r["x"]), n(r["y"])]
                       + ([n(r["dv"], 4), n(r["z"])] if lev else []))
