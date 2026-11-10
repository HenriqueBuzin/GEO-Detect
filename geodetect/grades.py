"""Grades espaciais comparáveis: quadrada métrica (5 km) e hexagonal H3.

Cada grade oferece a mesma interface:
    celula_dos_centroides(g)   célula do centroide de cada alerta (para CONTAGEM)
    intersecoes(g)             área de cada alerta em cada célula que ele toca (para ÁREA)
    vizinhos(celulas)          vizinhos imediatos: 6 no H3, 8 (Moore) no quadrado
    area_km2(celulas)          área real de cada célula
    poligonos(celulas)         polígonos das células no CRS métrico (para mapas)

Contagem por centroide e área por interseção são grandezas diferentes: um alerta
conta uma única vez na célula do centroide, mas sua área pode ser repartida entre
várias células, sem dupla contagem (as células de cada grade são uma partição).

Observação: o H3 é definido sobre WGS84. Os alertas estão em SIRGAS 2000 (EPSG:4674),
que coincide com WGS84 em escala submétrica; a conversão é feita com pyproj.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import cached_property

import geopandas as gpd
import h3
import numpy as np
import pandas as pd
import shapely
from pyproj import Transformer

from geodetect.dados import CELULA_M, CRS_METRICO

_PARA_METRICO = Transformer.from_crs("EPSG:4326", CRS_METRICO, always_xy=True)
_PARA_LONLAT = Transformer.from_crs(CRS_METRICO, "EPSG:4326", always_xy=True)


def _projetar(geom, transformer: Transformer):
    return shapely.transform(geom, lambda xy: np.column_stack(transformer.transform(xy[:, 0], xy[:, 1])))


class Grade:
    nome: str

    def celula_dos_centroides(self, g: gpd.GeoDataFrame) -> pd.Series: ...
    def intersecoes(self, g: gpd.GeoDataFrame) -> pd.DataFrame: ...
    def vizinhos(self, celulas) -> dict[str, list[str]]: ...
    def area_km2(self, celulas) -> pd.Series: ...
    def poligonos(self, celulas) -> gpd.GeoSeries: ...


@dataclass
class GradeQuadrada(Grade):
    lado_m: int = CELULA_M
    nome: str = field(init=False)

    def __post_init__(self):
        self.nome = f"quadrado_{self.lado_m / 1000:g}km"

    @staticmethod
    def _id(i, j) -> np.ndarray:
        return np.char.add(np.char.add(np.asarray(i).astype(str), "_"), np.asarray(j).astype(str))

    @staticmethod
    def _ij(celulas) -> np.ndarray:
        return np.array([c.split("_") for c in celulas], dtype=int).reshape(-1, 2)

    def celula_dos_centroides(self, g):
        c = g.geometry.centroid
        i = np.floor(c.x.to_numpy() / self.lado_m).astype(int)
        j = np.floor(c.y.to_numpy() / self.lado_m).astype(int)
        return pd.Series(self._id(i, j), index=g.index, name="celula")

    def intersecoes(self, g):
        linhas = []
        for chave, geom in zip(g["chave"].to_numpy(), g.geometry.to_numpy()):
            x0, y0, x1, y1 = geom.bounds
            i0, i1 = int(np.floor(x0 / self.lado_m)), int(np.floor(x1 / self.lado_m))
            j0, j1 = int(np.floor(y0 / self.lado_m)), int(np.floor(y1 / self.lado_m))
            for i in range(i0, i1 + 1):
                for j in range(j0, j1 + 1):
                    cel = shapely.box(i * self.lado_m, j * self.lado_m, (i + 1) * self.lado_m, (j + 1) * self.lado_m)
                    a = geom.intersection(cel).area
                    if a > 0:
                        linhas.append((chave, f"{i}_{j}", a / 1e6))
        return pd.DataFrame(linhas, columns=["chave", "celula", "area_km2"])

    def vizinhos(self, celulas):
        ij = self._ij(celulas)
        desloc = [(di, dj) for di in (-1, 0, 1) for dj in (-1, 0, 1) if (di, dj) != (0, 0)]
        return {c: [f"{i + di}_{j + dj}" for di, dj in desloc] for c, (i, j) in zip(celulas, ij)}

    def area_km2(self, celulas):
        return pd.Series((self.lado_m / 1000) ** 2, index=list(celulas))

    def poligonos(self, celulas):
        ij = self._ij(celulas)
        L = self.lado_m
        geoms = shapely.box(ij[:, 0] * L, ij[:, 1] * L, (ij[:, 0] + 1) * L, (ij[:, 1] + 1) * L)
        return gpd.GeoSeries(geoms, index=list(celulas), crs=CRS_METRICO)

    def celulas_por_quadrado(self, quadrados, lado_ref_m: int = CELULA_M) -> pd.Series:
        """Subcélulas de cada quadrado de referência (5 km). Exige que o lado divida 5 km."""
        if lado_ref_m % self.lado_m:
            raise ValueError(f"lado {self.lado_m} m não divide {lado_ref_m} m")
        n = lado_ref_m // self.lado_m
        out = {}
        for q in quadrados:
            i, j = map(int, q.split("_"))
            for a in range(n):
                for b in range(n):
                    out[f"{i * n + a}_{j * n + b}"] = q
        return pd.Series(out, name="quadrado")


@dataclass
class GradeH3(Grade):
    res: int
    nome: str = field(init=False)

    def __post_init__(self):
        self.nome = f"h3_r{self.res}"

    def celula_dos_centroides(self, g):
        c = g.geometry.centroid
        lon, lat = _PARA_LONLAT.transform(c.x.to_numpy(), c.y.to_numpy())
        return pd.Series([h3.latlng_to_cell(la, lo, self.res) for la, lo in zip(lat, lon)],
                         index=g.index, name="celula")

    def intersecoes(self, g):
        ll = g.to_crs("EPSG:4326")
        linhas = []
        for chave, geom_ll, geom_m in zip(g["chave"].to_numpy(), ll.geometry.to_numpy(), g.geometry.to_numpy()):
            forma = h3.geo_to_h3shape(geom_ll.__geo_interface__)
            # MultiPolygon: cada parte devolve suas células; a união evita dupla contagem
            cands = set(h3.h3shape_to_cells_experimental(forma, self.res, contain="overlap"))
            for cel in sorted(cands):
                a = geom_m.intersection(self._poligono_m(cel)).area
                if a > 0:
                    linhas.append((chave, cel, a / 1e6))
        return pd.DataFrame(linhas, columns=["chave", "celula", "area_km2"])

    def _poligono_m(self, cel: str):
        return self._cache_poligonos.setdefault(cel, _projetar(self._poligono_ll(cel), _PARA_METRICO))

    @staticmethod
    def _poligono_ll(cel: str):
        return shapely.Polygon([(lo, la) for la, lo in h3.cell_to_boundary(cel)])

    @cached_property
    def _cache_poligonos(self) -> dict:
        return {}

    def vizinhos(self, celulas):
        return {c: list(h3.grid_ring(c, 1)) for c in celulas}

    def area_km2(self, celulas):
        celulas = list(celulas)
        return pd.Series([h3.cell_area(c, unit="km^2") for c in celulas], index=celulas)

    def poligonos(self, celulas):
        celulas = list(celulas)
        return gpd.GeoSeries([self._poligono_m(c) for c in celulas], index=celulas, crs=CRS_METRICO)

    def celulas_por_quadrado(self, quadrados, lado_m: int = CELULA_M) -> pd.Series:
        """Células H3 cujo CENTRO cai em cada quadrado (partição da mesma região)."""
        out = {}
        for q in quadrados:
            i, j = map(int, q.split("_"))
            caixa = shapely.box(i * lado_m, j * lado_m, (i + 1) * lado_m, (j + 1) * lado_m)
            forma = h3.geo_to_h3shape(_projetar(caixa, _PARA_LONLAT).__geo_interface__)
            for c in h3.h3shape_to_cells(forma, self.res):
                out[c] = q
        return pd.Series(out, name="quadrado")


def grades_padrao() -> list[Grade]:
    """Quadrado de 5 km (referência), H3 6/7/8 e quadrados de controle com área próxima ao H3:
    2,5 km (6,25 km² ≈ H3 r7, 5,7 km²) e 1 km (1 km² ≈ H3 r8, 0,81 km²).
    Os controles separam o efeito da FORMA (hexágono × quadrado) do efeito da RESOLUÇÃO."""
    return [GradeQuadrada(), GradeH3(6), GradeH3(7), GradeH3(8), GradeQuadrada(2500), GradeQuadrada(1000)]
