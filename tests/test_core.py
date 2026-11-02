import numpy as np

from topolab.core.contours import contour_lines, is_master, make_levels
from topolab.core.surface import build_tin


def _grid(n=21, f=lambda x, y: x):
    xs, ys = np.meshgrid(np.linspace(0, 100, n), np.linspace(0, 100, n))
    x, y = xs.ravel(), ys.ravel()
    return np.column_stack([x, y, f(x, y)])


def test_plane_contours_are_exact_straight_lines():
    # Plano z = x: a curva de cota L deve ser a reta x = L (exato num TIN).
    tin = build_tin(_grid(f=lambda x, y: x))
    lines = contour_lines(tin, 37.5)
    assert len(lines) == 1
    xs = np.array([p[0] for p in lines[0]])
    assert np.allclose(xs, 37.5, atol=1e-9)
    ys = [p[1] for p in lines[0]]
    assert min(ys) == 0 and max(ys) == 100


def test_cone_contours_are_closed_rings():
    cx = cy = 50
    f = lambda x, y: 100 - np.hypot(x - cx, y - cy)
    tin = build_tin(_grid(n=61, f=f))
    lines = contour_lines(tin, 80.0)  # raio esperado = 20
    assert len(lines) == 1
    ring = np.array(lines[0])
    assert np.allclose(ring[0], ring[-1])  # fechada
    r = np.hypot(ring[:, 0] - cx, ring[:, 1] - cy)
    assert abs(r.mean() - 20) < 0.3


def test_levels_and_master():
    assert make_levels(1.2, 10.1, 2.5) == [2.5, 5.0, 7.5, 10.0]
    assert is_master(10.0, 2.5, 2) and not is_master(7.5, 2.5, 2)


def test_max_edge_removes_long_triangles():
    pts = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [100, 100, 0.0]])
    assert len(build_tin(pts).triangles) > len(build_tin(pts, max_edge=5).triangles)


def test_duplicates_are_dropped():
    pts = np.array([[0, 0, 1], [0, 0, 2], [1, 0, 0], [0, 1, 0.0]])
    assert len(build_tin(pts).points) == 3


# ---------------------------------------------------------------- fase 2
from topolab.core.volumes import volume_between, volume_vs_datum  # noqa: E402


def test_datum_plane_cut_and_fill_exact():
    # z = x em [0,100]^2, referência 50: corte = fill = 100 * 50*50/2 = 125000
    res = volume_vs_datum(build_tin(_grid(n=23, f=lambda x, y: x)), 50.0)
    assert abs(res.cut - 125000) < 1e-6 and abs(res.fill - 125000) < 1e-6
    assert abs(res.cut_area - 5000) < 1e-6 and abs(res.fill_area - 5000) < 1e-6
    assert abs(res.total_area - 10000) < 1e-6 and abs(res.net) < 1e-6


def test_datum_all_cut_and_all_fill():
    tin = build_tin(_grid(f=lambda x, y: 10 + 0 * x))
    assert abs(volume_vs_datum(tin, 4).cut - 6 * 10000) < 1e-6
    assert volume_vs_datum(tin, 4).fill == 0
    assert abs(volume_vs_datum(tin, 15).fill - 5 * 10000) < 1e-6


def test_datum_areas_partition_total():
    rng = np.random.default_rng(1)
    xy = rng.uniform(0, 100, (400, 2))
    tin = build_tin(np.column_stack([xy, 20 + 5 * np.sin(xy[:, 0] / 9) * np.cos(xy[:, 1] / 7)]))
    r = volume_vs_datum(tin, 21.0)
    assert abs(r.cut_area + r.fill_area - r.total_area) < 1e-6
    assert r.cut > 0 and r.fill > 0


def test_between_surfaces_constant_offset():
    a = build_tin(_grid(n=15, f=lambda x, y: 10 + 0 * x))
    b = build_tin(_grid(n=9, f=lambda x, y: 8 + 0 * x))
    r = volume_between(a, b)
    assert abs(r.cut - 2 * 10000) < 1e-6 and r.fill == 0


def test_between_surfaces_tilted_vs_flat():
    a = build_tin(_grid(n=21, f=lambda x, y: x))               # z = x
    rng = np.random.default_rng(2)
    xy = np.vstack([rng.uniform(0, 100, (150, 2)), [[0, 0], [100, 0], [0, 100], [100, 100]]])
    b = build_tin(np.column_stack([xy, np.full(len(xy), 50.0)]))  # plano z = 50
    r = volume_between(a, b)
    assert abs(r.cut - 125000) < 1e-4 and abs(r.fill - 125000) < 1e-4


def test_z_at_and_max_edge_hole():
    tin = build_tin(_grid(n=11, f=lambda x, y: 2 * x + y))
    z = tin.z_at([[10, 10], [33.3, 41.7], [500, 500]])
    assert abs(z[0] - 30) < 1e-9 and abs(z[1] - (2 * 33.3 + 41.7)) < 1e-9 and np.isnan(z[2])
    pts = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [1, 1, 0], [100, 0, 0], [100, 1, 0.0]])
    t = build_tin(pts, max_edge=3)
    assert np.isnan(t.z_at([[50, 0.5]])[0])


# ---------------------------------------------------------------- recorte por polígono
from topolab.core.region import Region  # noqa: E402


def _poly_area(pts):
    x, y = np.array(pts, float).T
    return 0.5 * abs(np.dot(x, np.roll(y, -1)) - np.dot(np.roll(x, -1), y))


def test_region_whole_surface_equals_unclipped():
    tin = build_tin(_grid(n=17, f=lambda x, y: x * 0.7 + 3 * np.sin(y / 11)))
    full = Region([([(-5, -5), (105, -5), (105, 105), (-5, 105)], [])])
    a, b = volume_vs_datum(tin, 30.0), volume_vs_datum(tin, 30.0, full)
    assert abs(a.cut - b.cut) < 1e-6 and abs(a.fill - b.fill) < 1e-6
    assert abs(a.total_area - b.total_area) < 1e-6


def test_region_rectangle_off_grid_is_exact():
    tin = build_tin(_grid(n=23, f=lambda x, y: x))  # z = x
    reg = Region([([(25, 0), (75, 0), (75, 100), (25, 100)], [])])
    r = volume_vs_datum(tin, 50.0, reg)
    assert abs(r.cut - 31250) < 1e-6 and abs(r.fill - 31250) < 1e-6
    assert abs(r.total_area - 5000) < 1e-6


def test_region_rotated_triangle_constant_surface():
    tin = build_tin(_grid(n=19, f=lambda x, y: 10 + 0 * x))
    poly = [(10, 10), (90, 20), (40, 80)]
    r = volume_vs_datum(tin, 0.0, Region([(poly, [])]))
    assert abs(r.cut - 10 * _poly_area(poly)) < 1e-6 and r.fill == 0


def test_region_with_hole_and_concave_l_shape():
    tin = build_tin(_grid(n=21, f=lambda x, y: 10 + 0 * x))
    sq = [(0, 0), (100, 0), (100, 100), (0, 100)]
    hole = [(40, 40), (60, 40), (60, 60), (40, 60)]
    r = volume_vs_datum(tin, 0.0, Region([(sq, [hole])]))
    assert abs(r.cut - 10 * (10000 - 400)) < 1e-6

    tin2 = build_tin(_grid(n=21, f=lambda x, y: x))  # L: corte 62500, aterro 125000 (datum 50)
    L = [(0, 0), (100, 0), (100, 50), (50, 50), (50, 100), (0, 100)]
    r2 = volume_vs_datum(tin2, 50.0, Region([(L, [])]))
    assert abs(r2.cut - 62500) < 1e-6 and abs(r2.fill - 125000) < 1e-6


def test_region_between_surfaces_and_multipolygon():
    a = build_tin(_grid(n=15, f=lambda x, y: 10 + 0 * x))
    b = build_tin(_grid(n=9, f=lambda x, y: 8 + 0 * x))
    p1 = [(10, 10), (30, 10), (30, 30), (10, 30)]
    p2 = [(50, 50), (80, 50), (80, 90), (50, 90)]
    r = volume_between(a, b, Region([(p1, []), (p2, [])]))
    assert abs(r.cut - 2 * (400 + 1200)) < 1e-6 and r.fill == 0


def test_region_matches_brute_force_on_random_terrain():
    rng = np.random.default_rng(7)
    xy = rng.uniform(0, 100, (500, 2))
    z = 20 + 6 * np.sin(xy[:, 0] / 13) + 4 * np.cos(xy[:, 1] / 9)
    tin = build_tin(np.vstack([np.column_stack([xy, z]), _grid(n=5, f=lambda x, y: 20 + 0 * x)]))
    poly = [(15, 20), (80, 10), (95, 70), (50, 90), (30, 60)]
    reg = Region([(poly, [])])
    r = volume_vs_datum(tin, 20.0, reg)
    g = np.linspace(0, 100, 701)[:-1] + 100 / 1400
    gx, gy = np.meshgrid(g, g)
    q = np.column_stack([gx.ravel(), gy.ravel()])
    ok = reg.contains(q)
    h = tin.z_at(q[ok]) - 20.0
    cell = (100 / 700) ** 2
    assert abs(r.cut - np.nansum(np.clip(h, 0, None)) * cell) / r.cut < 0.02
    assert abs(r.fill - np.nansum(np.clip(-h, 0, None)) * cell) / r.fill < 0.02


# ---------------------------------------------------------------- perfis e seções
from topolab.core.profiles import (  # noqa: E402
    Axis, cross_sections, format_station, make_stations, profile_along,
    section_areas, section_volumes,
)


def _plane_tin():
    return build_tin(_grid(n=41, f=lambda x, y: 2 * x + y))  # z = 2x + y


def test_axis_chainage_and_points():
    ax = Axis([(0, 0), (30, 0), (30, 40)])
    assert abs(ax.length - 70) < 1e-12
    p, t = ax.at([0, 15, 30, 50, 70])
    assert np.allclose(p, [[0, 0], [15, 0], [30, 0], [30, 20], [30, 40]])
    assert np.allclose(t[1], [1, 0]) and np.allclose(t[3], [0, 1])


def test_profile_on_plane_includes_vertices():
    ax = Axis([(10, 50), (60, 50), (60, 90)])  # L: 50 m + 40 m
    pr = profile_along(_plane_tin(), ax, 20.0)
    assert 50.0 in pr.station                       # vértice do eixo entra no perfil
    assert np.allclose(pr.z, 2 * pr.x + pr.y)       # plano: interpolação exata
    out = profile_along(_plane_tin(), Axis([(50, 50), (150, 50)]), 25.0)
    assert np.isnan(out.z[-1]) and np.isfinite(out.z[0])  # fora do TIN -> NaN


def test_sections_geometry_and_sign_convention():
    ax = Axis([(10, 50), (90, 50)])                 # sentido +x; direita = -y
    secs = cross_sections(_plane_tin(), ax, 20.0, 10.0, 2.5)
    assert [s.station for s in secs] == [0, 20, 40, 60, 80]
    s = secs[1]
    assert np.allclose(s.y, 50 - s.offsets) and np.allclose(s.x, 30)
    assert np.allclose(s.z, 2 * s.x + s.y)


def test_section_areas_and_average_end_area_volume():
    ax = Axis([(10, 50), (90, 50)])
    tin = _plane_tin()
    # z no eixo = 2x + 50; referência = cota do eixo na seção -> corte = aterro = 50
    secs_flat = cross_sections(tin, ax, 20.0, 10.0, 2.5)
    for s in secs_flat:
        c, f, ok = section_areas(s.offsets, s.z, s.z_axis)
        assert ok and abs(c - 50) < 1e-9 and abs(f - 50) < 1e-9
    # referência fixa 100: seções com z_axis < 100 (x < 25) viram aterro
    secs = cross_sections(tin, ax, 20.0, 10.0, 2.5, datum=100.0)
    assert secs[0].area_cut == 0 and secs[0].area_fill > 0
    vols = section_volumes(secs)
    assert len(vols) == 4 and all(v[4] for v in vols)
    assert abs(sum(v[2] for v in vols) - sum(
        (a.area_cut + b.area_cut) / 2 * 20 for a, b in zip(secs[:-1], secs[1:]))) < 1e-9


def test_section_areas_crossing_exact():
    # z - datum vai de -2 a +2 em 4 m: dois triângulos (base 2, altura 2) -> área 2 cada
    c, f, ok = section_areas([0, 4], [8, 12], 10)
    assert abs(c - 2) < 1e-12 and abs(f - 2) < 1e-12 and ok


def test_incomplete_sections_flagged_and_stations_format():
    ax = Axis([(50, 50), (150, 50)])
    secs = cross_sections(_plane_tin(), ax, 25.0, 5.0, 2.5, datum=0.0)
    assert secs[0].complete and not secs[-1].complete
    assert section_volumes(secs)[-1][4] is False
    assert format_station(125.0) == "6+05,00" and format_station(0) == "0+00,00"
    assert list(make_stations(50, 20)) == [0, 20, 40, 50]


# ---------------------------------------------------------------- importação de pontos
from topolab.core.importer import (  # noqa: E402
    PRESETS, decode_bytes, guess_delimiter, parse_points, to_float,
)


def test_import_semicolon_decimal_comma_with_header_and_latin1():
    raw = "Ponto;Leste;Norte;Cota;Descrição\nP1;500123,45;9823456,10;12,5;árvore\n" \
          "P2;500130,00;9823460,25;12,9;meio-fio\n".encode("cp1252")
    text, enc = decode_bytes(raw)
    assert enc == "cp1252" and "árvore" in text
    r = parse_points(text, PRESETS["Ponto, X, Y, Z, Descrição"])
    assert r.header and r.delimiter == ";" and r.decimal == ","
    assert np.allclose(r.xyz[0], [500123.45, 9823456.10, 12.5])
    assert r.ids == ["P1", "P2"] and r.desc[1] == "meio-fio"


def test_import_north_east_order_is_swapped_explicitly():
    text = "1 9823456.10 500123.45 12.5\n2 9823460.25 500130.00 12.9\n"
    r = parse_points(text, PRESETS["Ponto, N (Norte), E (Leste), Z"])
    assert r.delimiter == " " and not r.header
    assert np.allclose(r.xyz[0], [500123.45, 9823456.10, 12.5])  # X=Leste, Y=Norte


def test_import_comma_delimited_dot_decimal_and_tab():
    r = parse_points("1,100.5,200.5,10.25\n2,101.5,201.5,10.75\n", PRESETS["Ponto, X (Leste), Y (Norte), Z"])
    assert r.delimiter == "," and r.decimal == "." and np.allclose(r.xyz[1], [101.5, 201.5, 10.75])
    t = parse_points("100,5\t200,5\t10,25\n101,5\t201,5\t10,75\n", PRESETS["X (Leste), Y (Norte), Z"])
    assert t.delimiter == "\t" and t.decimal == "," and np.allclose(t.xyz[0], [100.5, 200.5, 10.25])


def test_import_skips_bad_lines_and_reports_them():
    text = "P1;1;2;3\nP2;abc;2;3\nP3;1;2\n# comentário\nP4;4;5;6\n"
    r = parse_points(text, PRESETS["Ponto, X (Leste), Y (Norte), Z"], delimiter=";", header=False)
    assert len(r.xyz) == 2 and r.n_skipped == 2 and r.skipped[0][0] == 2


def test_import_numbers_and_errors():
    assert to_float("1.234,56") == 1234.56 and to_float("1,234.56") == 1234.56
    assert to_float("12,5") == 12.5 and to_float("x") is None and to_float("nan") is None
    assert guess_delimiter(["a;b;c", "1;2;3"]) == ";"
    import pytest
    with pytest.raises(ValueError):
        parse_points("1;2;3\n", ("id", "x", "skip"))
    with pytest.raises(ValueError):
        parse_points("", PRESETS["X (Leste), Y (Norte), Z"])


# ---------------------------------------------------------------- poligonais
from topolab.core.angles import format_dms, parse_angle  # noqa: E402
from topolab.core.traverse import solve_traverse  # noqa: E402


def test_parse_and_format_angles():
    v = 123 + 45 / 60 + 30.5 / 3600
    for txt in ("123°45'30,5\"", "123 45 30.5", "123-45-30,5", "123:45:30.5"):
        assert abs(parse_angle(txt, "dms") - v) < 1e-12
    assert abs(parse_angle("123,5", "decimal") - 123.5) < 1e-12
    assert abs(parse_angle("123.4530", "ddd.mmss") - (123 + 45 / 60 + 30 / 3600)) < 1e-12
    assert abs(parse_angle("123.453050", "ddd.mmss") - v) < 1e-12
    assert abs(parse_angle("-10 30 0") + 10.5) < 1e-12
    assert format_dms(123 + 45 / 60 + 30 / 3600) == "123°45'30\""
    assert format_dms(29.99999999) == "30°00'00\""        # sem "29°59'60\""
    assert format_dms(10.5083333, 1) == "10°30'30,0\""
    import pytest
    for bad in ("", "abc", "12 75 00"):
        with pytest.raises(ValueError):
            parse_angle(bad, "dms")


def test_closed_square_perfect_data():
    # Quadrado percorrido no sentido horário; ângulos internos medidos à ESQUERDA.
    r = solve_traverse(list("ABCD"), [90] * 4, [100] * 4, "fechada", 0, 0, 0.0, turn="esquerda")
    assert np.allclose(r.azimuth, [0, 90, 180, 270]) and abs(r.ang_error_sec) < 1e-9
    assert np.allclose(r.x, [0, 0, 100, 100]) and np.allclose(r.y, [0, 100, 100, 0])
    assert abs(r.area - 10000) < 1e-9 and r.lin_error < 1e-9 and r.perimeter == 400
    # Os mesmos vértices com ângulos externos medidos à DIREITA (270°) dão o mesmo resultado.
    r2 = solve_traverse(list("ABCD"), [270] * 4, [100] * 4, "fechada", 0, 0, 0.0, turn="direita")
    assert np.allclose(r2.x, r.x) and np.allclose(r2.y, r.y)


def test_closed_with_errors_is_adjusted_and_closes():
    ang = [90 + 10 / 3600, 90 - 4 / 3600, 90 + 6 / 3600, 90 + 4 / 3600]   # erro = +16"
    dist = [100.02, 99.97, 100.03, 99.98]
    for method in ("bowditch", "transito"):
        r = solve_traverse(list("ABCD"), ang, dist, "fechada", 1000, 5000, 0.0,
                           turn="esquerda", method=method,
                           ang_tol_per_sqrt_n=20, min_precision=3000)
        assert abs(r.ang_error_sec - 16) < 1e-6 and abs(r.angle_adj.sum() - 360) < 1e-9
        assert r.angular_ok                     # tolerância 20"*sqrt(4)=40"
        assert abs(r.dE_adj.sum()) < 1e-9 and abs(r.dN_adj.sum()) < 1e-9
        assert r.lin_error > 0 and r.rel_precision == r.perimeter / r.lin_error
    tight = solve_traverse(list("ABCD"), ang, dist, "fechada", 0, 0, 0.0, turn="esquerda",
                           ang_tol_per_sqrt_n=2)
    assert not tight.angular_ok


def test_enquadrada_hits_known_end_and_azimuth():
    # Ré A(-50,0)->1(0,0): azimute 90. Estações (0,0),(100,0),(100,100),(0,100); vante B(-50,100): 270.
    kw = dict(mode="enquadrada", x0=0, y0=0, az0=90.0, turn="direita",
              x_end=0, y_end=100, az_end=270.0)
    ok = solve_traverse(list("1234"), [180, 90, 90, 180], [100, 100, 100], **kw)
    assert np.allclose(ok.x, [0, 100, 100, 0]) and np.allclose(ok.y, [0, 0, 100, 100])
    assert abs(ok.ang_error_sec) < 1e-9 and ok.lin_error < 1e-9
    bad = solve_traverse(list("1234"), [180, 90 + 12 / 3600, 90, 180],
                         [100.05, 100, 99.96], **kw)
    assert abs(bad.ang_error_sec - 12) < 1e-6
    assert abs(bad.x[-1] - 0) < 1e-9 and abs(bad.y[-1] - 100) < 1e-9   # chega no ponto conhecido
    assert bad.lin_error > 0


def test_open_traverse_has_no_adjustment_and_validation():
    r = solve_traverse(list("123"), [180, 90, 0], [10, 20], "aberta", 0, 0, 90.0, turn="direita")
    assert np.allclose(r.x, [0, 10, 10]) and np.allclose(r.y, [0, 0, 20]) and r.lin_error == 0
    import pytest
    with pytest.raises(ValueError):
        solve_traverse(list("AB"), [90, 90], [10, 10], "fechada", 0, 0, 0)
    with pytest.raises(ValueError):
        solve_traverse(list("ABC"), [90, 90, 90], [10, 0, 10], "fechada", 0, 0, 0)
    with pytest.raises(ValueError):
        solve_traverse(list("123"), [1, 2, 3], [1, 1], "enquadrada", 0, 0, 0)


def test_traverse_report_and_memorial():
    from topolab.core.traverse_report import memorial_text, traverse_report_html
    r = solve_traverse(["P1", "P2", "P3", "P4"], [90 + 8 / 3600, 90, 90, 90], [100, 100, 100.01, 100],
                       "fechada", 500000, 9800000, 0.0, turn="esquerda",
                       ang_tol_per_sqrt_n=20, min_precision=5000)
    h = traverse_report_html(r, "Teste", [("Modo", "fechada")])
    assert "Erro angular de fechamento" in h and "Precisão relativa" in h and "10.000" in h
    m = memorial_text(r, "Imóvel X", "SIRGAS 2000 / UTM 22S")
    assert m.startswith("IMÓVEL X") and "vértice P1" in m and "fechando o perímetro" in m
    assert m.count("deste, segue com azimute") == 4 and "E = 500.000,00 m" in m
    ab = solve_traverse(list("123"), [180, 90, 0], [10, 20], "aberta", 0, 0, 90.0)
    assert "fechando" not in memorial_text(ab)


# ---------------------------------------------------------------- DXF e raster
def test_grid_to_points_coordinates_step_and_nodata():
    from topolab.core.raster import grid_to_points
    arr = np.array([[1, 2, 3, 4], [5, -9999, 7, 8], [9, 10, np.nan, 12.0]])
    p = grid_to_points(arr, x_min=100, y_max=200, xres=2, yres=2, nodata=-9999)
    assert len(p) == 10                                        # 12 - nodata - NaN
    assert np.allclose(p[0], [101, 199, 1]) and np.allclose(p[-1], [107, 195, 12])
    q = grid_to_points(arr, 100, 200, 2, 2, step=2)
    assert len(q) == 3 and np.allclose(q[0], [101, 199, 1]) and np.allclose(q[1], [105, 199, 3])  # (2,2) é NaN
    import pytest
    with pytest.raises(ValueError):
        grid_to_points(arr, 0, 0, 1, 1, step=0)


def test_dxf_writer_roundtrip_with_independent_reader(tmp_path):
    ezdxf = __import__("pytest").importorskip("ezdxf")
    from topolab.core.dxf import DxfWriter, layer_name
    assert layer_name("Curvas de nível (1m)") == "CURVAS_DE_NIVEL__1M"
    w = DxfWriter()
    w.point("Pontos", 10, 20, 5.5)
    w.line("Eixo", (0, 0), (10, 10, 3))
    w.polyline("Curvas", [(0, 0, 100), (10, 0, 100), (10, 10, 100)])           # 3D
    w.polyline("Perimetro", [(0, 0), (10, 0), (10, 10), (0, 10)], closed=True)  # 2D fechada
    w.polyline("Curta", [(0, 0)])                                             # ignorada
    w.text("Pontos_txt", 10.3, 20.3, 5.5, 1.0, "P1 - cota 5,50 árvore")
    path = tmp_path / "t.dxf"
    w.save(str(path))
    doc = ezdxf.readfile(str(path))
    msp = doc.modelspace()
    kinds = sorted(e.dxftype() for e in msp)
    assert kinds == ["LINE", "POINT", "POLYLINE", "POLYLINE", "TEXT"]
    poly3d = [e for e in msp if e.dxftype() == "POLYLINE" and e.is_3d_polyline][0]
    assert [tuple(v.dxf.location) for v in poly3d.vertices][0] == (0, 0, 100)
    closed = [e for e in msp if e.dxftype() == "POLYLINE" and e.is_closed][0]
    assert len(list(closed.vertices)) == 4
    assert {"PONTOS", "EIXO", "CURVAS", "PERIMETRO", "PONTOS_TXT"} <= {l.dxf.name for l in doc.layers}
    assert doc.audit().errors == []


# ---------------------------------------------------------------- qualidade, mapas, memorial
def test_quality_checks_flag_each_problem():
    from topolab.core.quality import check_points
    g = _grid(n=11, f=lambda x, y: 0.5 * x + 100)          # plano suave, 121 pontos
    pts = [list(r) for r in g]
    pts[5][2] = 0.0                                          # cota zero
    pts.append([pts[20][0], pts[20][1], pts[20][2]])         # duplicado igual
    pts.append([pts[30][0], pts[30][1], pts[30][2] + 3])     # duplicado com cota diferente
    pts.append([pts[40][0] + 0.02, pts[40][1], pts[40][2]])  # muito próximo (2 cm)
    pts[60][2] += 60                                         # pico
    pts.append([1000.0, 1000.0, float("nan")])               # inválido
    names = [f"P{i}" for i in range(len(pts))]
    names[2] = names[3] = "REP"
    rep = check_points(np.array(pts), names, near_dist=0.05)
    c = rep.counts()
    assert c["cota_zero"] == 1 and rep.flags["cota_zero"][5]
    assert c["duplicado"] == 1 and rep.flags["duplicado"][len(g)]
    assert c["duplicado_cota_diferente"] == 2
    assert rep.flags["muito_proximo"][40] and rep.flags["muito_proximo"][len(g) + 2]
    # picos reais: cota zerada (5), pico injetado (60) e duplicado +3 m (índice len(g)+1)
    assert set(np.nonzero(rep.flags["pico"])[0]) == {60, len(g) + 1}   # a cota zero é só "cota zerada"
    assert c["nao_finito"] == 1 and c["id_repetido"] == 2
    assert len(check_points(g).flagged()) == 0          # plano limpo: nada sinalizado
    assert 5 in rep.flagged() and "cota_zero" in rep.kinds_of(5)


def test_slope_aspect_and_surface_area():
    from topolab.core.thematic import class_index, surface_area, triangle_stats
    tin = build_tin(_grid(n=11, f=lambda x, y: 0.1 * x))     # desce para oeste, 10 %
    st = triangle_stats(tin)
    assert np.allclose(st["slope_pct"], 10) and np.allclose(st["aspect"], 270)
    assert np.allclose(st["slope_deg"], np.degrees(np.arctan(0.1)))
    a2, a3 = surface_area(tin)
    assert abs(a2 - 10000) < 1e-6 and abs(a3 - 10000 * np.sqrt(1.01)) < 1e-6
    assert list(class_index([1, 5, 10, 30, 50, 90], [3, 8, 20, 45, 75])) == [0, 1, 2, 3, 4, 5]


def test_band_polygons_elevation_flood_and_cutfill():
    from topolab.core.thematic import band_polygons
    from topolab.core.volumes import difference_surface
    tin = build_tin(_grid(n=15, f=lambda x, y: x))           # z = x
    P, z = tin.points[tin.triangles][:, :, :2], tin.points[tin.triangles][:, :, 2]

    def areas(polys, nb):
        out = np.zeros(nb)
        for _, b, poly in polys:
            a = np.array(poly)
            out[b] += 0.5 * abs(np.dot(a[:, 0], np.roll(a[:, 1], -1)) - np.dot(np.roll(a[:, 0], -1), a[:, 1]))
        return out

    ar = areas(band_polygons(P, z, [25, 50, 75]), 4)         # faixas por elevação
    assert np.allclose(ar, [2500, 2500, 2500, 2500]) and abs(ar.sum() - 10000) < 1e-6
    fl = areas(band_polygons(P, z - 30, [0]), 2)             # inundação até a cota 30
    assert abs(fl[0] - 3000) < 1e-6
    assert abs(volume_vs_datum(tin, 30).fill - 45000) < 1e-6  # volume d'água
    other = build_tin(_grid(n=9, f=lambda x, y: 50 + 0 * x))
    pts, tri = difference_surface(tin, other)                # diferença = x - 50
    cf = areas(band_polygons(pts[tri][:, :, :2], pts[tri][:, :, 2], [0.0]), 2)
    assert abs(cf[0] - 5000) < 1e-6 and abs(cf[1] - 5000) < 1e-6   # aterro | corte


def test_memorial_roundtrip_and_route():
    from topolab.core.route import memorial_from_coords, parse_memorial, route_from_coords
    x = np.array([500000.0, 500123.45, 500201.10, 500090.77])
    y = np.array([9800000.0, 9800010.20, 9800150.85, 9800120.30])
    az, d = route_from_coords(x, y, True)
    assert len(az) == 4 and abs(d[0] - np.hypot(123.45, 10.20)) < 1e-9
    txt = memorial_from_coords(["P1", "P2", "P3", "P4"], x, y, True, "Imóvel", "SIRGAS 2000 / UTM 22S")
    g = parse_memorial(txt)
    assert g.closed and g.names == ["P1", "P2", "P3", "P4"]
    assert np.allclose(g.x, x, atol=0.02) and np.allclose(g.y, y, atol=0.02)
    assert g.misclosure < 0.05
    semcoord = "Inicia-se no vértice A; deste, segue com azimute de 90°00'00\" e distância de 10,5 m até o vértice B"
    h = parse_memorial(semcoord, start=(100.0, 200.0))
    assert not h.closed and np.allclose(h.x, [100, 110.5]) and np.allclose(h.y, [200, 200])
    import pytest
    with pytest.raises(ValueError):
        parse_memorial(semcoord)                 # sem coordenadas iniciais
    with pytest.raises(ValueError):
        parse_memorial("texto qualquer")


# ---------------------------------------------------------------- linhas de quebra e limite
def _edges(tin):
    t = tin.triangles
    e = np.sort(np.concatenate([t[:, [0, 1]], t[:, [1, 2]], t[:, [2, 0]]]), axis=1)
    return set(map(tuple, e.tolist()))


def _chain_is_edges(tin, a, b, tol=1e-9):
    """Os pontos do TIN sobre o segmento a-b, em ordem, são ligados por arestas consecutivas?"""
    P = tin.points[:, :2]
    a, b = np.array(a, float), np.array(b, float)
    d = b - a
    L2 = float(d @ d)
    t = (P - a) @ d / L2
    dist = np.abs(d[0] * (P[:, 1] - a[1]) - d[1] * (P[:, 0] - a[0])) / np.sqrt(L2)
    on = np.nonzero((dist < tol) & (t > -1e-12) & (t < 1 + 1e-12))[0]
    on = on[np.argsort(t[on])]
    ed = _edges(tin)
    return len(on) >= 2 and all((min(p, q), max(p, q)) in ed for p, q in zip(on[:-1], on[1:])), len(on)


def _total_area(tin):
    P = tin.points[tin.triangles]
    a, b, c = P[:, 0, :2], P[:, 1, :2], P[:, 2, :2]
    cr = (b[:, 0] - a[:, 0]) * (c[:, 1] - a[:, 1]) - (c[:, 0] - a[:, 0]) * (b[:, 1] - a[:, 1])
    return 0.5 * np.abs(cr).sum(), cr


def test_breakline_becomes_edges_and_valid_triangulation():
    pts = _grid(n=21, f=lambda x, y: x)                       # z = x, malha de 5 em 5
    line = np.array([[12.3, 7.7, np.nan], [88.1, 71.9, np.nan]])
    plain, forced = build_tin(pts), build_tin(pts, breaklines=[line])
    assert not _chain_is_edges(plain, line[0, :2], line[1, :2])[0]      # sem a linha: não é aresta
    ok, n_on = _chain_is_edges(forced, line[0, :2], line[1, :2])
    assert ok and n_on >= 3
    area, cr = _total_area(forced)
    assert abs(area - 10000) < 1e-6 and (cr != 0).all()                  # cobre o mesmo domínio, sem sobrepor
    assert np.allclose(forced.z_at([[50.0, 50.0]]), 50.0)                # linha sem cota: segue o MDT


def test_breakline_elevation_is_honored():
    pts = _grid(n=21, f=lambda x, y: x)
    line = np.array([[20.0, 50.0, 200.0], [80.0, 50.0, 210.0]])         # cota própria (crista)
    t = build_tin(pts, breaklines=[line])
    assert abs(t.z_at([[50.0, 50.0]])[0] - 205.0) < 1e-9 and abs(t.z_at([[80.0, 50.0]])[0] - 210.0) < 1e-9
    assert abs(build_tin(pts).z_at([[50.0, 50.0]])[0] - 50.0) < 1e-9     # sem a linha seria 50


def test_breakline_through_collinear_grid_points_and_polyline():
    pts = _grid(n=21, f=lambda x, y: 0.2 * x + 10)
    t = build_tin(pts, breaklines=[np.array([[0.0, 50.0], [100.0, 50.0]]),            # passa por vértices
                                   np.array([[10.0, 10.0], [30.0, 25.0], [60.0, 20.0]])])
    assert _chain_is_edges(t, (0, 50), (100, 50))[0]
    assert _chain_is_edges(t, (10, 10), (30, 25))[0] and _chain_is_edges(t, (30, 25), (60, 20))[0]
    assert abs(_total_area(t)[0] - 10000) < 1e-6


def test_crossing_breaklines_give_clear_error():
    import pytest
    pts = _grid(n=11, f=lambda x, y: x)
    with pytest.raises(ValueError, match="se cruzam"):   # duas linhas com cota própria: cota ambígua
        build_tin(pts, breaklines=[np.array([[13.0, 11.0, 50.0], [87.0, 93.0, 50.0]]),
                                   np.array([[11.0, 90.0, 60.0], [91.0, 12.0, 60.0]])])
    ok = build_tin(pts, breaklines=[np.array([[10.0, 10.0], [50.0, 50.0], [90.0, 90.0]]),
                                    np.array([[10.0, 90.0], [50.0, 50.0], [90.0, 10.0]])])
    assert _chain_is_edges(ok, (10, 10), (50, 50))[0] and _chain_is_edges(ok, (50, 50), (90, 10))[0]


def test_crossing_error_points_to_the_crossing():
    import re

    import pytest
    pts = _grid(n=11, f=lambda x, y: x)
    a, b, c, d = map(np.array, ([13.0, 11.0], [87.0, 93.0], [11.0, 90.0], [91.0, 12.0]))
    with pytest.raises(ValueError) as err:
        build_tin(pts, breaklines=[np.array([[*a, 50.0], [*b, 50.0]]), np.array([[*c, 60.0], [*d, 60.0]])])
    x, y = map(float, re.search(r"\((-?[\d.]+); (-?[\d.]+)\)", str(err.value)).groups())
    def cross(u, v):
        return u[0] * v[1] - u[1] * v[0]
    t = cross(c - a, d - c) / cross(b - a, d - c)
    assert np.allclose((x, y), a + t * (b - a), atol=1e-3)   # o ponto do cruzamento, não um vértice


def test_boundary_and_hole_limit_the_tin_exactly():
    from topolab.core.region import Region
    pts = _grid(n=21, f=lambda x, y: x)
    outer = [(17.3, 21.1), (83.7, 19.4), (79.2, 77.8), (22.5, 81.6)]
    hole = [(40.0, 40.0), (60.0, 40.0), (60.0, 60.0), (40.0, 60.0)]
    t = build_tin(pts, boundary=Region([(outer, [hole])]))
    expect = 0.5 * abs(np.dot([p[0] for p in outer], np.roll([p[1] for p in outer], -1)) -
                       np.dot(np.roll([p[0] for p in outer], -1), [p[1] for p in outer])) - 400
    assert abs(_total_area(t)[0] - expect) < 1e-6                        # nenhum triângulo atravessa o limite
    z = t.z_at([[50.0, 50.0], [5.0, 5.0], [30.0, 50.0]])
    assert np.isnan(z[0]) and np.isnan(z[1]) and abs(z[2] - 30.0) < 1e-9  # furo e fora do limite: NaN


def test_breaklines_improve_volume_on_a_ditch():
    # Terreno plano z=10 com uma vala em V (fundo z=8) ao longo de y=50, levantada só por pontos esparsos.
    xs, ys = np.meshgrid(np.linspace(0, 100, 11), np.linspace(0, 100, 11))
    pts = np.column_stack([xs.ravel(), ys.ravel(), np.full(121, 10.0)])
    pts = pts[np.abs(pts[:, 1] - 50) > 1e-9]                              # tira a linha y=50 do levantamento
    base = volume_vs_datum(build_tin(pts), 10.0)
    vala = np.array([[0.0, 50.0, 8.0], [100.0, 50.0, 8.0]])
    forced = build_tin(pts, breaklines=[vala])
    assert abs(forced.z_at([[50.0, 50.0]])[0] - 8.0) < 1e-9
    assert volume_vs_datum(forced, 10.0).fill > base.fill + 1.0           # a vala passa a existir no volume


# --- Platô com taludes --------------------------------------------------------------------
def _flat_tin(z=100.0, half=80.0, n=33):
    g = np.linspace(-half, half, n)
    X, Y = np.meshgrid(g, g)
    return build_tin(np.column_stack([X.ravel(), Y.ravel(), np.full(X.size, z)]))


def _square(half=10.0):
    from topolab.core.region import Region
    return Region([([(-half, -half), (half, -half), (half, half), (-half, half)], [])])


def test_platform_fill_square_matches_closed_form():
    # Terreno plano, platô 20 x 20 a 3 m acima, aterro 1,5:1 -> prisma + 4 cunhas + cone nos cantos
    import math
    from topolab.core.platform import _dist_to_rings, platform_earthwork
    a, h, m = 20.0, 3.0, 1.5
    r = platform_earthwork(_flat_tin(), _square(), m_cut=1.0, m_fill=m, level=103.0)
    vol = a * a * h + 2 * a * m * h * h + math.pi / 3 * m * m * h ** 3
    area = a * a + 4 * a * m * h + math.pi * (m * h) ** 2
    assert abs(r.fill / vol - 1) < 1e-4 and r.cut < 1e-9
    assert abs(r.footprint_area / area - 1) < 1e-4 and abs(r.platform_area - 400) < 1e-9
    assert r.complete and [o.kind for o in r.offsets] == ["Aterro"]
    toe = r.offsets[0]
    assert np.allclose(_dist_to_rings(toe.xyz[:, :2], _square()), m * h, atol=2e-3)  # pé a m·h da borda
    assert np.allclose(toe.xyz[:, 2], 100.0) and abs(toe.length - (4 * a + 2 * math.pi * m * h)) < 0.05


def test_platform_cut_square_matches_closed_form():
    import math
    from topolab.core.platform import platform_earthwork
    r = platform_earthwork(_flat_tin(), _square(), m_cut=1.0, m_fill=1.5, level=97.0)
    vol = 400 * 3 + 2 * 20 * 1.0 * 9 + math.pi / 3 * 27
    assert abs(r.cut / vol - 1) < 1e-4 and r.fill < 1e-9
    assert [o.kind for o in r.offsets] == ["Corte"]


def test_platform_concave_corner_matches_closed_form():
    # Platô em L (5 cantos convexos e 1 côncavo): V = A·h + P·m·h²/2 + (5π/2 - 2)·m²·h³/6
    import math
    from topolab.core.platform import platform_earthwork
    from topolab.core.region import Region
    L = Region([([(0, 0), (30, 0), (30, 10), (10, 10), (10, 30), (0, 30)], [])])
    r = platform_earthwork(_flat_tin(), L, m_fill=1.5, level=102.0)
    vol = 500 * 2 + 120 * 1.5 * 4 / 2 + (2.5 * math.pi - 2) * 2.25 * 8 / 6
    assert abs(r.fill / vol - 1) < 1e-4


def test_platform_balance_level():
    # Terreno em rampa, platô centrado e taludes iguais: por simetria, equilíbrio na cota do centro
    from topolab.core.platform import platform_earthwork
    g = np.linspace(-80, 80, 33)
    X, Y = np.meshgrid(g, g)
    ramp = build_tin(np.column_stack([X.ravel(), Y.ravel(), 100 + 0.1 * X.ravel()]))
    r = platform_earthwork(ramp, _square(), m_cut=1.5, m_fill=1.5)
    assert r.balanced and abs(r.level - 100.0) < 1e-3 and abs(r.cut / r.fill - 1) < 1e-3
    assert sorted(o.kind for o in r.offsets) == ["Aterro", "Corte"]
    r = platform_earthwork(ramp, _square(), m_cut=1.5, m_fill=1.5, factor=1.25)
    assert r.level < 100.0 and abs(r.cut / (1.25 * r.fill) - 1) < 1e-3 and abs(r.balance) < 0.5


def test_platform_flags_slopes_outside_the_survey():
    from topolab.core.platform import platform_earthwork
    r = platform_earthwork(_flat_tin(half=12, n=13), _square(), m_fill=1.5, level=103.0)
    assert not r.complete            # o pé do aterro ficaria a 14,5 m, além do MDT (12 m)
    assert platform_earthwork(_flat_tin(half=16, n=17), _square(), m_fill=1.5, level=103.0).complete


def test_platform_vertical_wall_and_zero_height():
    from topolab.core.platform import platform_earthwork
    wall = platform_earthwork(_flat_tin(), _square(), m_cut=0, m_fill=0, level=103.0)
    assert abs(wall.fill - 1200) < 1e-6 and abs(wall.footprint_area - 400) < 0.01
    zero = platform_earthwork(_flat_tin(), _square(), level=100.0)
    assert zero.cut < 1e-6 and zero.fill < 1e-6 and len(zero.offsets) == 1


def test_platform_design_contours_skip_the_platform_level():
    from topolab.core.platform import platform_earthwork
    g = np.linspace(-80, 80, 33)
    X, Y = np.meshgrid(g, g)
    ramp = build_tin(np.column_stack([X.ravel(), Y.ravel(), 100 + 0.1 * X.ravel()]))
    r = platform_earthwork(ramp, _square(), m_cut=1.0, m_fill=1.5, level=100.5, contour_interval=0.5)
    levels = {c[0] for c in r.contours}
    assert levels and 100.5 not in levels and {99.5, 101.0} <= levels


def test_platform_rejects_platform_outside_the_survey():
    import pytest
    from topolab.core.platform import platform_earthwork
    from topolab.core.region import Region
    far = Region([([(500, 500), (520, 500), (520, 520), (500, 520)], [])])
    with pytest.raises(ValueError, match="fora da área do MDT"):
        platform_earthwork(_flat_tin(), far, level=100.0)


def test_platform_with_walls_equals_clipped_datum_volume():
    # Talude 0 nos dois lados = platô sem talude: igual ao volume contra cota com recorte (exato)
    from topolab.core.platform import platform_earthwork
    from topolab.core.region import Region
    from topolab.core.volumes import volume_vs_datum
    g = np.linspace(-80, 80, 33)
    X, Y = np.meshgrid(g, g)
    tin = build_tin(np.column_stack([X.ravel(), Y.ravel(), 100 + 0.1 * X.ravel() + 0.03 * Y.ravel()]))
    reg = Region([([(-13, -7), (17, -9), (12, 14), (-9, 11)], [])])
    wall, exact = platform_earthwork(tin, reg, 0, 0, 100.4), volume_vs_datum(tin, 100.4, reg)
    assert abs(wall.cut - exact.cut) < 1e-9 and abs(wall.fill - exact.fill) < 1e-9


def test_polygon_area_precise_with_utm_coordinates():
    # Com coordenadas UTM a fórmula do laço sem centralizar errava décimos de m²
    from fractions import Fraction
    from topolab.core.route import polygon_area
    rng = np.random.default_rng(1)
    t = np.sort(rng.uniform(0, 2 * np.pi, 200))
    rad = rng.uniform(150, 400, 200)
    x = np.round(512345.678 + rad * np.cos(t), 3)
    y = np.round(9123456.789 + rad * np.sin(t), 3)
    n = len(x)
    exact = abs(sum(Fraction(x[i]) * Fraction(y[(i + 1) % n]) - Fraction(x[(i + 1) % n]) * Fraction(y[i])
                    for i in range(n))) / 2
    assert abs(polygon_area(list(x), list(y)) - float(exact)) < 1e-4


def test_platform_same_result_in_utm_coordinates():
    import math
    from topolab.core.platform import platform_earthwork
    from topolab.core.region import Region
    out = []
    for e0, n0 in ((0.0, 0.0), (500000.0, 9000000.0)):
        xs = np.arange(0, 201, 5.0)
        X, Y = np.meshgrid(xs, xs)
        Z = 50 + 0.06 * X + 0.03 * Y + 2.5 * np.sin(X / 35) * np.cos(Y / 45)
        tin = build_tin(np.column_stack([X.ravel() + e0, Y.ravel() + n0, Z.ravel()]))
        a = math.radians(20)
        ring = [(e0 + 100 + u * math.cos(a) - v * math.sin(a), n0 + 100 + u * math.sin(a) + v * math.cos(a))
                for u, v in [(-20, -12.5), (20, -12.5), (20, 12.5), (-20, 12.5)]]
        out.append(platform_earthwork(tin, Region([(ring, [])]), 1.0, 1.5, factor=1.2))
    a, b = out
    assert abs(a.level - b.level) < 1e-4 and abs(a.cut - b.cut) < 0.05 and abs(a.fill - b.fill) < 0.05
    assert abs(a.footprint_area - b.footprint_area) < 0.05 and abs(b.platform_area - 1000) < 1e-6


def test_unambiguous_crossings_get_a_vertex_automatically():
    # Linha de quebra que ultrapassa o limite do MDT, e duas linhas sem cota própria que se cruzam
    from topolab.core.region import Region
    pts = _grid(n=11, f=lambda x, y: 0.1 * x + 100)
    bound = Region([([(5, 5), (95, 5), (95, 95), (5, 95)], [])])
    crest = np.array([[0.0, 20.0, 120.0], [100.0, 57.0, 120.0]])         # sai do limite nos dois lados
    t = build_tin(pts, breaklines=[crest], boundary=bound)
    # o cruzamento com o limite (x = 5) ganhou vértice com a cota da crista, não a do MDT
    x5 = t.points[np.isclose(t.points[:, 0], 5.0) & np.isclose(t.points[:, 1], 20 + 0.37 * 5)]
    assert len(x5) == 1 and abs(x5[0, 2] - 120.0) < 1e-9
    assert abs(_total_area(t)[0] - 90 * 90) < 1e-6
    t2 = build_tin(pts, breaklines=[np.array([[13.0, 11.0], [87.0, 93.0]]),
                                    np.array([[11.0, 90.0], [91.0, 12.0]])])
    assert abs(_total_area(t2)[0] - 100 * 100) < 1e-6


def test_volume_between_honours_breaklines_of_both_surfaces():
    # A: crista oblíqua (só nas pontas); B: vala que cruza a crista; limite de A com furo
    from topolab.core.region import Region
    from topolab.core.volumes import difference_surface, volume_between, volume_vs_datum

    def ridge(x, y):
        return 103 - 0.08 * np.abs((y - 0.37 * x - 20) / np.hypot(1, 0.37))

    def valley(x, y):
        return 99 + 0.05 * np.abs((x - 0.2 * y - 60) / np.hypot(1, 0.2))
    g = np.arange(0, 101, 10.0)
    X, Y = np.meshgrid(g, g)
    g2 = np.arange(-5, 106, 7.0)                       # B levantada numa malha deslocada
    X2, Y2 = np.meshgrid(g2, g2)
    crest = np.array([[0, 20, 103.0], [100, 57, 103.0]])
    A = build_tin(np.column_stack([X.ravel(), Y.ravel(), ridge(X.ravel(), Y.ravel())]), breaklines=[crest])
    flat = build_tin(np.column_stack([X2.ravel(), Y2.ravel(), np.full(X2.size, 100.0)]))
    exact = volume_vs_datum(A, 100.0).cut
    assert abs(volume_between(A, flat).cut - exact) < 1e-6
    from topolab.core.volumes import _result_from_heights
    pts, tri = difference_surface(A, flat, use_lines=False)   # como era antes: atravessa a crista
    assert abs(_result_from_heights(pts[:, :2], tri, pts[tri, 2]).cut - exact) > 1.0
    bound = Region([([(5, 5), (95, 5), (95, 95), (5, 95)], [[(15, 60), (30, 60), (30, 75), (15, 75)]])])
    A2 = build_tin(np.column_stack([X.ravel(), Y.ravel(), ridge(X.ravel(), Y.ravel())]),
                   breaklines=[crest], boundary=bound)
    B2 = build_tin(np.column_stack([X2.ravel(), Y2.ravel(), valley(X2.ravel(), Y2.ravel())]),
                   breaklines=[np.array([[60, 0, 99.0], [80, 100, 99.0]])])
    r = volume_between(A2, B2)
    # referência: integração fina das funções exatas dentro do limite, fora do furo
    f = np.linspace(5, 95, 3001)
    c = (f[:-1] + f[1:]) / 2
    XX, YY = np.meshgrid(c, c)
    h = (ridge(XX, YY) - valley(XX, YY)) * ~((XX > 15) & (XX < 30) & (YY > 60) & (YY < 75))
    ca = (90 / 3000) ** 2
    assert abs(r.total_area - (90 * 90 - 15 * 15)) < 1e-6
    assert abs(r.cut - np.clip(h, 0, None).sum() * ca) < 0.05
    assert abs(r.fill - np.clip(-h, 0, None).sum() * ca) < 0.05


def test_boundary_vertices_follow_the_terrain_and_uniform_offset_is_exact():
    # Pontos inseridos ao longo do limite (sem cota própria) pegam a cota do MDT, não a média dos cantos
    from topolab.core.region import Region
    from topolab.core.volumes import volume_between
    xs, ys = np.meshgrid(np.linspace(0, 100, 15), np.linspace(0, 100, 15))
    P = np.column_stack([xs.ravel(), ys.ravel(), 100 + 0.05 * xs.ravel() + 3 * np.sin(ys.ravel() / 15)])
    bound = Region([([(5, 5), (95, 5), (95, 95), (5, 95)], [[(40, 40), (60, 40), (60, 60), (40, 60)]])])
    plain = build_tin(P)
    A = build_tin(P, breaklines=[np.array([[10, 10.0], [30, 80.0]])], boundary=bound)
    edge = np.isclose(A.points[:, 0], 5) | np.isclose(A.points[:, 0], 95)
    assert edge.sum() > 4 and np.allclose(A.points[edge, 2], plain.z_at(A.points[edge, :2]), atol=1e-9)
    B = build_tin(P - [0, 0, 0.8], breaklines=[np.array([[70, 0.0], [60, 100.0]])])
    r = volume_between(A, B)          # B = A - 0,8 nos mesmos pontos
    assert abs(r.cut - 0.8 * 7700) < 1e-6 and r.fill < 1e-6 and abs(r.total_area - 7700) < 1e-6


# --- Nivelamento trigonométrico na poligonal --------------------------------------------
def test_reduce_observations_slope_and_zenith():
    import math
    from topolab.core.traverse import reduce_observations
    dh, dv = reduce_observations([100.0, 50.0], [80.0, 95.0], hi=[1.6, 1.5], hs=[1.8, 1.5], curvature=False)
    assert np.allclose(dh, [100 * math.sin(math.radians(80)), 50 * math.sin(math.radians(95))])
    assert np.allclose(dv, [100 * math.cos(math.radians(80)) - 0.2, 50 * math.cos(math.radians(95))])
    _, dvc = reduce_observations([1000.0], [90.0])            # (1 - 0,13)·1000²/(2·6371000)
    assert abs(dvc[0] - 0.87 * 1e6 / (2 * 6371000)) < 1e-12
    import pytest
    with pytest.raises(ValueError, match="zenital"):
        reduce_observations([10.0], [181.0])


def test_closed_traverse_elevations_and_vertical_closure():
    from topolab.core.traverse import solve_traverse
    dv_true = np.array([2.0, -1.5, 0.7, -1.2])                 # soma zero
    dv = dv_true.copy()
    dv[1] += 0.02                                              # 2 cm de erro
    r = solve_traverse(list("ABCD"), [90] * 4, [100.0] * 4, "fechada", 0, 0, 90, dv=dv, z0=50,
                       v_tol_mm_per_sqrt_km=50)
    assert abs(r.v_error - 0.02) < 1e-12 and r.vertical_ok and abs(r.v_tol - 0.05 * np.sqrt(0.4)) < 1e-12
    assert np.allclose(r.z, [50, 51.995, 50.51, 51.205])      # erro distribuído pelas distâncias
    assert abs(r.dv_adj.sum()) < 1e-12
    r2 = solve_traverse(list("ABCD"), [90] * 4, [100.0] * 4, "fechada", 0, 0, 90, dv=dv + [0, 0.1, 0, 0],
                        z0=50, v_tol_mm_per_sqrt_km=50)
    assert not r2.vertical_ok


def test_framed_traverse_closes_on_final_elevation():
    from topolab.core.traverse import solve_traverse
    r = solve_traverse(["A", "B", "C"], [180, 180, 180], [100.0, 100.0], "enquadrada", 0, 0, 0,
                       x_end=0, y_end=200, az_end=0, dv=[1.0, 1.04], z0=10, z_end=12.0)
    assert abs(r.v_error - 0.04) < 1e-12 and np.allclose(r.z, [10, 10.98, 12.0])


# --- Importação de DXF ---------------------------------------------------------------------
def _survey_dxf(path, version="R2010"):
    ezdxf = __import__("pytest").importorskip("ezdxf")
    doc = ezdxf.new(version)
    msp = doc.modelspace()
    blk = doc.blocks.new(name="PTO")
    blk.add_circle((0, 0), 0.2)
    blk.add_attdef("PONTO", (0.3, 0.3))
    blk.add_attdef("COTA", (0.3, -0.3))
    msp.add_point((10, 10, 101.25), dxfattribs={"layer": "PONTOS_3D"})
    ins = msp.add_blockref("PTO", (20, 10), dxfattribs={"layer": "PONTOS_BLOCO"})
    ins.add_attrib("PONTO", "P7", (20.3, 10.3))
    ins.add_attrib("COTA", "102,40", (20.3, 9.7))
    msp.add_circle((30, 10), 0.2, dxfattribs={"layer": "PONTOS_2D"})
    msp.add_text("103,15", dxfattribs={"layer": "COTAS", "insert": (30.5, 10.4)})
    msp.add_text("104,90", dxfattribs={"layer": "COTAS", "insert": (80, 80)})       # sem ponto perto
    msp.add_text("12", dxfattribs={"layer": "COTAS", "insert": (30.2, 9.6)})        # nº do ponto, não cota
    msp.add_mtext("{\\fArial|b0;Cota\\P}105,5", dxfattribs={"layer": "NOTAS", "insert": (0, 50)})
    msp.add_lwpolyline([(0, 0), (40, 0), (40, 5)], dxfattribs={"layer": "CURVAS", "elevation": 100.0})
    msp.add_polyline3d([(0, 20, 99.0), (40, 25, 98.5)], dxfattribs={"layer": "TALUDE"})
    msp.add_lwpolyline([(-5, -5), (50, -5), (50, 60), (-5, 60)], close=True, dxfattribs={"layer": "LIMITE"})
    msp.add_spline([(0, 0), (5, 5), (10, 0)], dxfattribs={"layer": "CURVAS"})
    doc.layouts.get("Layout1").add_point((1, 1, 1), dxfattribs={"layer": "PONTOS_3D"})  # espaço do papel
    doc.saveas(path)


def test_read_dxf_entities_and_layers(tmp_path):
    from topolab.core.dxf_read import clean_mtext, number_in_text, read_dxf
    path = tmp_path / "lev.dxf"
    _survey_dxf(str(path))
    d = read_dxf(str(path))
    lay = d.layers()
    assert lay["PONTOS_3D"]["POINT"] == 1                     # o ponto do papel ficou de fora
    assert lay["PONTOS_BLOCO"]["INSERT"] == 1 and lay["COTAS"]["TEXT"] == 3
    assert d.unsupported["SPLINE"] == 1
    ins = next(e for e in d.entities if e.kind == "INSERT")
    assert ins.attribs == {"PONTO": "P7", "COTA": "102,40"} and ins.block == "PTO"
    lw = next(e for e in d.entities if e.kind == "LWPOLYLINE" and e.layer == "CURVAS")
    assert np.allclose(lw.xyz[:, 2], 100.0) and len(lw.xyz) == 3
    p3 = next(e for e in d.entities if e.layer == "TALUDE")
    assert np.allclose(p3.xyz, [[0, 20, 99.0], [40, 25, 98.5]])
    assert next(e for e in d.entities if e.layer == "LIMITE").closed
    assert clean_mtext("{\\fArial|b0;Cota\\P}105,5") == "Cota 105,5"
    assert number_in_text("103,15") == 103.15 and number_in_text("C=103.150 m") == 103.15
    assert number_in_text("12") is None and number_in_text("PT 12") is None


def test_build_survey_from_dxf_roles(tmp_path):
    from topolab.core.dxf_read import build_survey, guess_roles, read_dxf
    path = tmp_path / "lev.dxf"
    _survey_dxf(str(path))
    d = read_dxf(str(path))
    roles = guess_roles(d)
    assert roles["PONTOS_3D"] == roles["PONTOS_BLOCO"] == roles["PONTOS_2D"] == "pontos"
    assert roles["COTAS"] == "cotas" and roles["LIMITE"] == "limite" and roles["CURVAS"] == "linhas"
    sv = build_survey(d, roles, text_radius=1.0)
    pts = {p[0]: p for p in sv.points}
    assert pts["1"][3] == 101.25 and pts["1"][6] == "geometria"
    assert pts["P7"][3] == 102.40 and pts["P7"][6] == "atributo"
    assert pts["3"][3] == 103.15 and pts["3"][6] == "texto"                 # círculo + texto vizinho
    assert any(p[3] == 104.90 and p[6] == "texto (sem ponto)" for p in sv.points)
    assert sv.stats["sem_cota"] == 0 and len(sv.polygons) == 1 and len(sv.lines) == 2
    sv2 = build_survey(d, roles, text_radius=1.0, texts_as_points=False, line_vertices_as_points=True)
    assert not any(p[6] == "texto (sem ponto)" for p in sv2.points)
    assert sum(p[6] == "vértice de linha" for p in sv2.points) == 3 + 2


def test_dxf_export_then_import_round_trip(tmp_path):
    from topolab.core.dxf import DxfWriter
    from topolab.core.dxf_read import read_dxf
    w = DxfWriter()
    w.point("PONTOS", 500000.123, 9000000.456, 101.5)
    w.text("PONTOS_TXT", 500000.4, 9000000.8, 101.5, 1.0, "P1")
    w.polyline("CURVAS", [(0, 0, 100.0), (10, 0, 100.0), (10, 10, 100.0)], closed=True)
    path = tmp_path / "rt.dxf"
    w.save(str(path))
    d = read_dxf(str(path))
    p = next(e for e in d.entities if e.kind == "POINT")
    assert np.allclose(p.xyz[0], [500000.123, 9000000.456, 101.5])
    pl = next(e for e in d.entities if e.layer == "CURVAS")
    assert pl.closed and np.allclose(pl.xyz[:, 2], 100.0) and len(pl.xyz) == 3
    assert next(e for e in d.entities if e.kind == "TEXT").text == "P1"


def test_read_dxf_rejects_binary():
    import pytest
    from topolab.core.dxf_read import read_dxf
    with pytest.raises(ValueError, match="binário"):
        read_dxf(b"AutoCAD Binary DXF\r\n\x1a\x00" + bytes(range(40)))


def test_spike_next_to_zero_elevation_is_still_found():
    # Um ponto com cota zero ao lado de um pico não pode esconder o pico
    from topolab.core.quality import check_points
    xs, ys = np.meshgrid(np.arange(0, 300, 30.0), np.arange(0, 300, 30.0))
    xyz = np.column_stack([xs.ravel(), ys.ravel(), 200 + 0.05 * xs.ravel()])
    i_zero, i_spike = 44, 45                      # vizinhos
    xyz[i_zero, 2] = 0.0
    xyz[i_spike, 2] += 15.0
    rep = check_points(xyz)
    assert rep.flags["cota_zero"][i_zero] and rep.flags["pico"][i_spike]
    assert rep.flags["pico"].sum() == 1           # o zero é "cota zerada", não pico
    two = xyz.copy()
    two[i_zero, 2] = 200 + 0.05 * two[i_zero, 0] - 9.0   # dois picos vizinhos
    rep2 = check_points(two)
    assert rep2.flags["pico"][i_zero] and rep2.flags["pico"][i_spike]


def test_platform_final_contours_are_not_fragmented():
    # Terreno com ruído de 2 cm: cada cota do terreno final deve sair como uma curva contínua
    import math
    from topolab.core.platform import platform_earthwork
    from topolab.core.region import Region
    rng = np.random.default_rng(1)
    g = np.arange(-300, 301, 30.0)
    X, Y = np.meshgrid(g, g)
    X = X.ravel() + rng.uniform(-8, 8, X.size)
    Y = Y.ravel() + rng.uniform(-8, 8, Y.size)
    Z = 200 + 0.04 * X + 0.03 * Y + 2 * np.sin(X / 90) + rng.normal(0, 0.02, X.size)
    a = math.radians(25)
    rect = [(u * math.cos(a) - v * math.sin(a), u * math.sin(a) + v * math.cos(a))
            for u, v in [(-40, -25), (40, -25), (40, 25), (-40, 25)]]
    r = platform_earthwork(build_tin(np.column_stack([X, Y, Z])), Region([(rect, [])]), 1.0, 1.5,
                           contour_interval=0.5)
    levels = [c[0] for c in r.contours]
    assert len(levels) >= 10 and len(levels) == len(set(levels))     # uma peça por cota


def test_dxf_layer_names_drop_accents_instead_of_letters():
    from topolab.core.dxf import layer_name
    assert layer_name("2 - curvas de nível (1 m)") == "2_-_CURVAS_DE_NIVEL__1_M"
    assert layer_name("Platô: off-set") == "PLATO__OFF-SET"


# ---------------------------------------------------------------- 0.14: classes juntadas
def _grid_mesh(n=31, size=100.0):
    from scipy.spatial import Delaunay
    xs, ys = np.meshgrid(np.linspace(0, size, n), np.linspace(0, size, n))
    xy = np.column_stack([xs.ravel(), ys.ravel()])
    return xy, Delaunay(xy).simplices


def _ring_area(r):
    x, y = r[:, 0], r[:, 1]
    return 0.5 * np.sum(x * np.roll(y, -1) - np.roll(x, -1) * y)


def test_dissolved_bands_rings_and_areas():
    from topolab.core.dissolve import dissolved_bands, polygons_area
    from topolab.core.thematic import band_polygons
    xy, tri = _grid_mesh()
    v = np.hypot(xy[:, 0] - 50, xy[:, 1] - 50)          # cone: faixas são anéis concêntricos
    edges = [10.0, 20.0, 30.0]
    bands = dissolved_bands(xy, v, tri, edges)
    old = {}
    for _, b, poly in band_polygons(xy[tri], v[tri], edges):
        old[b] = old.get(b, 0.0) + abs(_ring_area(np.array(poly)))
    assert sorted(bands) == [0, 1, 2, 3]
    for b, polys in bands.items():
        assert abs(polygons_area(polys) - old[b]) < 1e-6 * old[b]
    assert len(bands[0]) == 1 and bands[0][0][1] == []  # disco central, sem furo
    assert len(bands[1]) == 1 and len(bands[1][0][1]) == 1   # anel: um externo, um furo
    for polys in bands.values():
        for outer, holes in polys:
            assert _ring_area(outer) > 0 and all(_ring_area(h) < 0 for h in holes)


def test_dissolved_classes_checkerboard_simple_rings():
    from topolab.core.dissolve import dissolved_classes, polygons_area
    xy, tri = _grid_mesh(21)
    cls = np.random.default_rng(1).integers(0, 3, len(tri))
    out = dissolved_classes(xy, tri, cls)
    assert abs(sum(polygons_area(p) for p in out.values()) - 100.0 * 100.0) < 1e-6
    for polys in out.values():
        for outer, holes in polys:
            for r in [outer] + holes:                  # nenhum anel passa duas vezes num vértice
                assert len({tuple(p) for p in r}) == len(r)


def test_dissolved_bands_integral_is_volume():
    from topolab.core.dissolve import dissolved_bands
    xy, tri = _grid_mesh()
    v = xy[:, 0] / 100.0 - 0.5                          # plano de -0,5 a +0,5 m
    _, vol = dissolved_bands(xy, v, tri, [0.0], integrate=True)
    # metade negativa: integral de (x/100 - 0,5) em x de 0 a 50, largura 100 = -1250
    assert abs(vol[0] + 1250.0) < 1e-6 and abs(vol[1] - 1250.0) < 1e-6


def test_tolerance_edges():
    from topolab.core.thematic import tolerance_edges
    e, still = tolerance_edges([-2, -1, -0.5, 0, 0.5, 1, 2], 0.05)
    assert e == [-2, -1, -0.5, -0.05, 0.05, 0.5, 1, 2] and still == 4
    e, still = tolerance_edges([-1, 0, 0.02, 1], 0.05)   # 0,02 cai dentro da tolerância
    assert e == [-1, -0.05, 0.05, 1] and still == 2
    e, _ = tolerance_edges([0], 0)                        # no mínimo 1 mm
    assert e == [-0.001, 0.001]


def test_conform_long_boundary_few_rounds(monkeypatch):
    """Limite com lados longos sobre pontos densos: as arestas faltantes são divididas de uma
    vez (Gabriel), com poucas triangulações, e todas entram no TIN."""
    import topolab.core.breaklines as B
    from topolab.core.region import Region
    calls = []
    orig = B._delaunay
    monkeypatch.setattr(B, "_delaunay", lambda p: calls.append(len(p)) or orig(p))
    rng = np.random.default_rng(3)
    xy = rng.uniform(0, 1000, (4000, 2)) + [500000, 9000000]
    xyz = np.column_stack([xy, 100 + 0.01 * (xy[:, 0] - 500000)])
    ring = np.array([[500050, 9000050], [500950, 9000080], [500900, 9000950], [500070, 9000900]], float)
    tin = build_tin(xyz, boundary=Region([(ring, [])]))
    assert len(calls) <= 4
    # a área do TIN recortado é a do polígono (nenhum lado do limite foi atravessado)
    P = tin.points[tin.triangles][:, :, :2]
    area = 0.5 * np.abs((P[:, 1, 0] - P[:, 0, 0]) * (P[:, 2, 1] - P[:, 0, 1])
                     - (P[:, 2, 0] - P[:, 0, 0]) * (P[:, 1, 1] - P[:, 0, 1])).sum()
    assert abs(area - abs(_ring_area(ring - ring.mean(0)))) < 1e-3


# --- 0.16: bermas ----------------------------------------------------------------------------
def _benched_closed_form(a, D, slope):
    """Volume de corte de um platô quadrado a×a rebaixado D num terreno plano, com o talude
    `slope` (Slope): prisma + integral de (D - rise(d))·(4a + 2πd) em d de 0 até o off-set."""
    R = slope.run(D)
    d = np.linspace(0, R, 400001)
    f = (D - slope.rise(d)) * (4 * a + 2 * np.pi * d)
    return a * a * D + float(np.sum((f[1:] + f[:-1]) / 2 * np.diff(d))), R


def test_slope_rise_and_run_with_benches():
    from topolab.core.platform import Slope
    s = Slope(1.5, bench_h=4.0, bench_w=2.0)            # período: 6 m de talude + 2 m de berma
    assert np.allclose(s.rise([0, 3, 6, 7, 8, 11]), [0, 2, 4, 4, 4, 6])
    assert abs(s.run(4.0) - 6.0) < 1e-12 and abs(s.run(6.0) - 11.0) < 1e-12
    assert [b[:2] for b in s.bench_distances(10)] == [(1, 4.0), (2, 8.0)]
    assert Slope(1.0).run(3.0) == 3.0 and not Slope(1.0, 5.0, 0).benched


def test_platform_cut_with_benches_matches_closed_form():
    from topolab.core.platform import Slope, platform_earthwork
    D, h, w = 10.0, 4.0, 2.0                             # 10 m de corte: 2 bermas (a 4 e 8 m)
    r = platform_earthwork(_flat_tin(z=100.0, half=80.0), _square(), m_cut=1.0, m_fill=1.5,
                           level=100.0 - D, bench_h=h, bench_w=w)
    vol, R = _benched_closed_form(20.0, D, Slope(1.0, h, w))
    assert abs(r.cut / vol - 1) < 2e-3 and r.fill < 1e-9
    assert r.benches == {"Corte": 2}
    crest = [o for o in r.offsets if o.kind == "Corte"]
    assert len(crest) == 1 and abs(crest[0].length - (80 + 2 * np.pi * R)) < 0.2   # off-set a R da borda
    bench = [o for o in r.offsets if o.kind == "Berma de corte"]
    assert len(bench) == 4                               # 2 bermas × (borda externa + interna)
    assert sorted({round(float(o.xyz[0, 2]), 6) for o in bench}) == [94.0, 98.0]


def test_platform_benches_rejected_with_vertical_wall():
    import pytest
    from topolab.core.platform import platform_earthwork
    with pytest.raises(ValueError):
        platform_earthwork(_flat_tin(), _square(), m_cut=0.0, level=97.0, bench_h=2.0, bench_w=1.0)
