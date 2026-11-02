"""Exportação de perfil e seções para CSV (padrão BR: ';' e vírgula decimal)."""
import csv

import numpy as np

from .profiles import format_station


def _num(v, decimals=3, decimal=","):
    if v is None or not np.isfinite(v):
        return ""
    return f"{v:.{decimals}f}".replace(".", decimal)


def write_profile_csv(path, profile, decimal=","):
    with open(path, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh, delimiter=";")
        w.writerow(["ESTACA", "DISTANCIA", "X", "Y", "COTA"])
        for s, x, y, z in zip(profile.station, profile.x, profile.y, profile.z):
            w.writerow([format_station(s), _num(s, 3, decimal), _num(x, 3, decimal),
                        _num(y, 3, decimal), _num(z, 3, decimal)])


def write_sections_csv(path, sections, decimal=","):
    with open(path, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh, delimiter=";")
        w.writerow(["ESTACA", "DISTANCIA", "DESLOCAMENTO", "X", "Y", "COTA"])
        for sec in sections:
            for o, x, y, z in zip(sec.offsets, sec.x, sec.y, sec.z):
                w.writerow([format_station(sec.station), _num(sec.station, 3, decimal),
                            _num(o, 3, decimal), _num(x, 3, decimal), _num(y, 3, decimal),
                            _num(z, 3, decimal)])
