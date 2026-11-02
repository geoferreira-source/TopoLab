"""Relatório HTML simples de volumes."""
import html
from datetime import datetime

from .volumes import VolumeResult


def fmt(x, decimals=3):
    """Formata número no padrão brasileiro (1.234,567)."""
    s = f"{x:,.{decimals}f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


DEFAULT_NOTE = ("Corte = terreno acima da referência; aterro = abaixo. Cálculo exato por "
                "triângulo do TIN. Para duas superfícies, usa um TIN composto sobre os vértices "
                "de ambas (aproximação nas interseções entre as superfícies).")


def volume_report_html(title, params, result: VolumeResult, note=None, extra=None, warning=None):
    """`params`: lista de (rótulo, valor) com os dados de entrada usados.

    note: texto do rodapé sobre o método (padrão: volumes sobre TIN).
    extra: linhas (rótulo, valor) acrescentadas ao fim da tabela de resultado.
    warning: aviso em destaque acima do resultado.
    """
    esc = html.escape
    rows_in = "".join(f"<tr><td>{esc(str(k))}</td><td>{esc(str(v))}</td></tr>" for k, v in params)
    rows_extra = "".join(f"<tr><td>{esc(str(k))}</td><td></td><td class=\"n\">{esc(str(v))}</td></tr>"
                         for k, v in (extra or []))
    warn = f"<p class=\"w\">{esc(warning)}</p>" if warning else ""
    saldo = "sobra de material" if result.net > 0 else "falta de material" if result.net < 0 else "equilibrado"
    return f"""<!DOCTYPE html>
<html lang="pt-BR"><head><meta charset="utf-8"><title>{esc(title)}</title>
<style>
body{{font-family:Arial,Helvetica,sans-serif;margin:24px;color:#222}}
h2{{color:#2f5d3a;margin-bottom:4px}} small{{color:#666}}
table{{border-collapse:collapse;margin:12px 0;min-width:360px}}
td,th{{border:1px solid #ccc;padding:6px 12px;text-align:left}}
th{{background:#eef3ea}} td.n{{text-align:right}}
p.w{{color:#a5281b;font-weight:bold}}
</style></head><body>
<h2>{esc(title)}</h2>
<small>Gerado em {datetime.now().strftime('%d/%m/%Y %H:%M')} pelo TopoLab</small>
<h3>Dados de entrada</h3><table>{rows_in}</table>
{warn}<h3>Resultado</h3>
<table>
<tr><th></th><th>Volume (un.&sup3;)</th><th>Área em planta (un.&sup2;)</th></tr>
<tr><td>Corte</td><td class="n">{fmt(result.cut)}</td><td class="n">{fmt(result.cut_area)}</td></tr>
<tr><td>Aterro</td><td class="n">{fmt(result.fill)}</td><td class="n">{fmt(result.fill_area)}</td></tr>
<tr><th>Saldo (corte &minus; aterro)</th><th class="n">{fmt(result.net)}</th><th>{saldo}</th></tr>
<tr><td>Área total considerada</td><td></td><td class="n">{fmt(result.total_area)}</td></tr>
{rows_extra}</table>
<p><small>Unidades = unidades do CRS (m, m&sup2;, m&sup3; em CRS projetado em metros).
{esc(note or DEFAULT_NOTE)} Confira os resultados antes de uso profissional.</small></p>
</body></html>"""
