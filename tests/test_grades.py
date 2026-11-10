"""Geometria e adjacência das grades (dados SINTÉTICOS)."""

import h3
import numpy as np
import pytest
import shapely

from conftest import X0, Y0
from geodetect.grades import GradeH3, GradeQuadrada, grades_padrao


@pytest.mark.parametrize("grade", grades_padrao(), ids=lambda gr: gr.nome)
def test_area_conservada_sem_dupla_contagem(grade, alertas_sinteticos):
    inter = grade.intersecoes(alertas_sinteticos)
    soma = inter.groupby("chave")["area_km2"].sum().reindex(alertas_sinteticos["chave"]).to_numpy()
    np.testing.assert_allclose(soma, alertas_sinteticos["area_km2"].to_numpy(), rtol=1e-9)
    assert not inter.duplicated(["chave", "celula"]).any()


def test_multipoligono_nao_duplica_celulas_h3(alertas_sinteticos):
    """Regressão: partes de um MultiPolygon na mesma célula H3 eram contadas várias vezes."""
    multi = alertas_sinteticos.iloc[[2]]
    for res in (7, 8):
        inter = GradeH3(res).intersecoes(multi)
        assert inter["area_km2"].sum() == pytest.approx(multi["area_km2"].iloc[0], rel=1e-9)


def test_quadrado_cruzando_divisas():
    g5 = GradeQuadrada()
    import geopandas as gpd
    from geodetect.dados import CRS_METRICO
    poly = shapely.box(X0 + 4_800, Y0 + 4_800, X0 + 5_300, Y0 + 5_300)
    inter = g5.intersecoes(gpd.GeoDataFrame({"chave": [0]}, geometry=[poly], crs=CRS_METRICO))
    assert len(inter) == 4


@pytest.mark.parametrize("grade", grades_padrao(), ids=lambda gr: gr.nome)
def test_centroide_esta_entre_as_celulas_intersectadas(grade, alertas_sinteticos):
    cent = grade.celula_dos_centroides(alertas_sinteticos)
    inter = grade.intersecoes(alertas_sinteticos)
    for chave, cel in zip(alertas_sinteticos["chave"], cent):
        if alertas_sinteticos.geometry.iloc[chave].contains(alertas_sinteticos.geometry.iloc[chave].centroid):
            assert cel in set(inter.loc[inter["chave"] == chave, "celula"])


def test_vizinhos_h3_seis_e_adjacentes():
    for res in (6, 7, 8):
        c = h3.latlng_to_cell(-6.0, -56.5, res)
        viz = GradeH3(res).vizinhos([c])[c]
        assert len(viz) == 6 and not h3.is_pentagon(c)
        assert all(h3.are_neighbor_cells(c, v) for v in viz)


def test_sem_pentagonos_no_para():
    pent = {p for r in (6, 7, 8) for p in h3.get_pentagons(r)}
    for res in (6, 7, 8):
        cel = GradeH3(res).celulas_por_quadrado(["80_570", "81_571"]).index
        assert not set(cel) & pent


def test_vizinhos_quadrado_moore_simetricos():
    g = GradeQuadrada()
    viz = g.vizinhos(["10_20"])["10_20"]
    assert len(viz) == 8 and "10_20" not in viz
    assert all("10_20" in g.vizinhos([v])[v] for v in viz)


def test_subdivisao_quadrados():
    m = GradeQuadrada(2500).celulas_por_quadrado(["3_4"])
    assert sorted(m.index) == ["6_8", "6_9", "7_8", "7_9"]
    with pytest.raises(ValueError):
        GradeQuadrada(3000).celulas_por_quadrado(["3_4"])


def test_h3_particiona_regiao_com_area_proxima():
    """Células H3 com centro nos quadrados: partição sem repetição e área total próxima."""
    quad = [f"{i}_{j}" for i in range(80, 90) for j in range(565, 575)]
    for res in (7, 8):
        m = GradeH3(res).celulas_por_quadrado(quad)
        assert m.index.is_unique
        area = GradeH3(res).area_km2(m.index).sum()
        assert area == pytest.approx(25 * len(quad), rel=0.03)
