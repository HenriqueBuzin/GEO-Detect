"""Testes das grades planas deslocáveis do script 11 (análise exploratória de decisão da grade).
Todos os pontos usados aqui são SINTÉTICOS."""

import numpy as np

from conftest import RAIZ, X0, Y0, carregar_script

mod = carregar_script("11_decisao_grade")
rng = np.random.default_rng(0)
XS, YS = X0 + rng.uniform(0, 40_000, 5_000), Y0 + rng.uniform(0, 40_000, 5_000)


def test_script11_le_so_desenvolvimento():
    fonte = (RAIZ / "scripts" / "11_decisao_grade.py").read_text(encoding="utf-8")
    assert 'g = g[g["view_date"] <= DEV[1]].copy()' in fonte


def test_hexagono_plano_e_voronoi_dos_centros():
    hx = mod.HexPlano(6.25, 321.0, 654.0)
    q, r = hx._qr(XS, YS)
    c = np.column_stack(hx._centro(q, r))
    p = np.column_stack([XS, YS])
    d0 = np.hypot(*(p - c).T)
    for a, b in mod.HexPlano._DIRS:
        assert (d0 <= np.hypot(*(p - np.column_stack(hx._centro(q + a, r + b))).T) + 1e-6).all()
    assert np.isclose(3 * np.sqrt(3) / 2 * hx.s ** 2 / 1e6, 6.25)


def test_vizinhos_planos_simetricos():
    for gr, n in ((mod.HexPlano(6.25), 6), (mod.Quadrada(2500, 100, 200), 8), (mod.Quadrada(2500, viz="vn"), 4)):
        cel = np.unique(gr.celula_de(XS, YS))
        viz = gr.vizinhos(cel)
        assert viz.shape == (len(cel), n)
        assert all(c in set(gr.vizinhos(np.array([v]))[0]) for c, v in zip(cel[:50], viz[:50, 0]))


def test_distancia_a_borda_limites():
    sq = mod.Quadrada(2500, 700, 300)
    d = sq.dist_borda(XS, YS)
    assert (d >= 0).all() and d.max() <= 1250 + 1e-6
    hx = mod.HexPlano(6.25, 10, 20)
    d = hx.dist_borda(XS, YS)
    assert (d >= -1e-6).all() and d.max() <= hx.a + 1e-6


def test_deslocamento_zero_coincide_com_grade_do_protocolo():
    from geodetect.grades import GradeQuadrada
    import geopandas as gpd
    import shapely
    pts = gpd.GeoDataFrame(geometry=shapely.points(XS[:200], YS[:200]), crs="ESRI:102033")
    ref = GradeQuadrada(2500).celula_dos_centroides(pts).to_numpy()
    mine = mod.Quadrada(2500).celula_de(XS[:200], YS[:200])
    ij = np.array([s.split("_") for s in ref], dtype=np.int64)
    np.testing.assert_array_equal(mine, mod.cod(ij[:, 0], ij[:, 1]))


def test_universo_plano_quatro_subcelulas_por_quadrado_com_deslocamento():
    quads = ["80_570", "81_570", "80_571"]
    cel, sq = mod.universo_plano(mod.Quadrada(2500, 900, 1700), quads)
    assert len(cel) == 4 * len(quads)
