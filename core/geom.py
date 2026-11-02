"""Pequenas funções geométricas compartilhadas."""
import numpy as np


def signed_area(x, y):
    """Área com sinal (positiva no sentido anti-horário) pela fórmula do laço (shoelace).

    As coordenadas são centradas antes da soma: com coordenadas UTM (~10^6 a 10^7) as somas
    parciais chegariam a ~10^16 e perderiam casas decimais (erros de décimos de m² em
    polígonos com centenas de vértices).
    """
    x = np.asarray(x, dtype=float).ravel()
    y = np.asarray(y, dtype=float).ravel()
    if len(x) < 3:
        return 0.0
    x = x - x.mean()
    y = y - y.mean()
    return 0.5 * float(np.dot(x, np.roll(y, -1)) - np.dot(np.roll(x, -1), y))
