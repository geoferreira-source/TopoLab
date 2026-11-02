"""Verificação de qualidade de pontos cotados (sem dependência do QGIS)."""
from dataclasses import dataclass

import numpy as np
from scipy.spatial import cKDTree

KINDS = {
    "nao_finito": "coordenada ou cota inválida",
    "cota_zero": "cota zerada",
    "duplicado": "XY repetido (mesma cota)",
    "duplicado_cota_diferente": "XY repetido com cotas diferentes",
    "muito_proximo": "muito próximo de outro ponto",
    "pico": "cota destoa dos vizinhos",
    "id_repetido": "identificador repetido",
}


@dataclass
class QualityReport:
    n: int
    flags: dict  # tipo -> array bool (n,)

    def counts(self):
        return {k: int(v.sum()) for k, v in self.flags.items()}

    def flagged(self):
        any_flag = np.zeros(self.n, dtype=bool)
        for v in self.flags.values():
            any_flag |= v
        return np.nonzero(any_flag)[0]

    def kinds_of(self, i):
        return [k for k, v in self.flags.items() if v[i]]


def check_points(xyz, names=None, zero_tol=0.0, near_dist=0.05, spike_k=8, spike_nmad=6.0,
                 spike_min_abs=0.02):
    """Procura problemas comuns que distorcem o MDT e os volumes.

    zero_tol: |cota| <= zero_tol conta como cota zerada.
    near_dist: pontos distintos a menos que isso são sinalizados (0 desliga).
    spike_k / spike_nmad / spike_min_abs: um ponto é 'pico' se sua cota difere do plano ajustado
    aos k vizinhos mais que spike_nmad vezes o desvio robusto (MAD) dos resíduos, e mais que
    spike_min_abs (mesma unidade da cota), e se é o maior resíduo da vizinhança.
    """
    xyz = np.asarray(xyz, dtype=float).reshape(-1, 3)
    n = len(xyz)
    flags = {k: np.zeros(n, dtype=bool) for k in KINDS}
    finite = np.isfinite(xyz).all(axis=1)
    flags["nao_finito"] = ~finite
    idx = np.nonzero(finite)[0]
    P = xyz[idx]

    flags["cota_zero"][idx[np.abs(P[:, 2]) <= zero_tol]] = True

    if len(P):
        key = np.round(P[:, :2], 6)
        _, inv, cnt = np.unique(key, axis=0, return_inverse=True, return_counts=True)
        inv = inv.ravel()
        for g in np.nonzero(cnt > 1)[0]:
            members = np.nonzero(inv == g)[0]
            if np.ptp(P[members, 2]) > 1e-6:
                flags["duplicado_cota_diferente"][idx[members]] = True
            else:
                flags["duplicado"][idx[members[1:]]] = True

    if near_dist and len(P) > 1:
        pairs = cKDTree(P[:, :2]).query_pairs(near_dist, output_type="ndarray")
        if len(pairs):
            d = np.hypot(*(P[pairs[:, 0], :2] - P[pairs[:, 1], :2]).T)
            pairs = pairs[d > 1e-6]  # distância zero já é duplicado
            flags["muito_proximo"][idx[pairs.ravel()]] = True

    # Picos: plano local (mínimos quadrados) nos k vizinhos, que respeita a inclinação do
    # terreno. Cotas zeradas ficam fora da vizinhança (distorceriam o plano), e a busca é
    # repetida sem os picos já achados, para que um erro grosseiro não esconda outro ao lado.
    cand = np.nonzero(~flags["cota_zero"][idx])[0]
    for _ in range(5):
        if len(cand) <= spike_k + 1:
            break
        Q = P[cand]
        xy = Q[:, :2]
        _, nb = cKDTree(xy).query(xy, k=spike_k + 1)
        nbr = nb[:, 1:]
        dx, dy = xy[nbr, 0] - xy[:, None, 0], xy[nbr, 1] - xy[:, None, 1]
        A = np.stack([np.ones_like(dx), dx, dy], axis=2)                 # (n, k, 3)
        ata = np.einsum("nki,nkj->nij", A, A)
        atb = np.einsum("nki,nk->ni", A, Q[nbr, 2])
        ata = ata + 1e-10 * np.einsum("nii->ni", ata)[:, :, None] * np.eye(3)
        pred = np.linalg.solve(ata, atb[:, :, None])[:, 0, 0]            # cota prevista no ponto
        resid = Q[:, 2] - pred
        ar = np.abs(resid)
        mad = np.median(np.abs(resid - np.median(resid))) * 1.4826
        thr = max(spike_nmad * mad, spike_min_abs)
        # só o máximo local: o pico contamina o plano dos vizinhos, que não são sinalizados
        new = (ar > thr) & (ar >= ar[nbr].max(axis=1))
        if not new.any():
            break
        flags["pico"][idx[cand[new]]] = True
        cand = cand[~new]

    if names is not None:
        names = [str(x).strip() for x in names]
        seen = {}
        for i, nm in enumerate(names):
            if nm:
                seen.setdefault(nm, []).append(i)
        for members in seen.values():
            if len(members) > 1:
                flags["id_repetido"][members] = True
    return QualityReport(n, flags)


ADVICE = {
    "nao_finito": "Corrija ou remova: impede o cálculo do TIN.",
    "cota_zero": "Confirme se é real; cotas zeradas por falha de coleta distorcem MDT e volumes.",
    "duplicado": "Remova as repetições (não alteram o resultado, mas poluem o levantamento).",
    "duplicado_cota_diferente": "Decida qual cota vale: o TIN guarda só a primeira.",
    "muito_proximo": "Verifique se são o mesmo ponto medido duas vezes ou erro de digitação.",
    "pico": "Confira em campo ou no croqui: pode ser erro de cota ou feição real (poste, vala).",
    "id_repetido": "Renomeie para manter identificadores únicos.",
}


def quality_html(rep: QualityReport, title="Verificação dos pontos", examples=None):
    """Resumo em HTML; `examples`: lista de (nome, x, y, z, problemas) dos primeiros sinalizados."""
    import html
    rows = "".join(
        f"<tr><td>{html.escape(KINDS[k])}</td><td style='text-align:right'>{c}</td>"
        f"<td>{html.escape(ADVICE[k])}</td></tr>" for k, c in rep.counts().items() if c)
    body = rows or "<tr><td colspan=3>Nenhum problema encontrado pelas verificações feitas.</td></tr>"
    ex = ""
    if examples:
        ex = "<h3>Primeiros pontos sinalizados</h3><table border=1 cellpadding=4 style='border-collapse:collapse'>" \
             "<tr><th>Ponto</th><th>X</th><th>Y</th><th>Cota</th><th>Problemas</th></tr>" + "".join(
                 f"<tr><td>{html.escape(str(n))}</td><td>{x:.3f}</td><td>{y:.3f}</td><td>{z:.3f}</td>"
                 f"<td>{html.escape(p)}</td></tr>" for n, x, y, z, p in examples) + "</table>"
    return (f"<h2>{html.escape(title)}</h2><p>{rep.n} pontos analisados, "
            f"{len(rep.flagged())} sinalizados.</p>"
            f"<table border=1 cellpadding=4 style='border-collapse:collapse'>"
            f"<tr><th>Verificação</th><th>Pontos</th><th>O que fazer</th></tr>{body}</table>{ex}"
            f"<p><small>Sinalização automática: não prova erro. Um ponto pode estar em mais de uma "
            f"categoria.</small></p>")
