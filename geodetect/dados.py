"""Carga e preparo padronizado dos alertas DETER, compartilhado por todos os scripts."""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely

CRS_METRICO = "ESRI:102033"  # South America Albers Equal Area Conic (área e distância em metros)
CELULA_M = 5_000
SLIVER_KM2 = 0.001  # 0,1 ha: fragmento de recorte municipal, não um alerta
ENTRADA_PADRAO = Path("data/raw/deter_amz_mineracao_pa.geojson")
LIMITE_PADRAO = Path("data/raw/limite_pa_ibge.geojson")

# Divisão temporal (ver README, "Decisão sobre o recorte experimental")
DEV = ("2024-01-01", "2025-06-30")
TESTE = ("2025-07-01", "2026-09-30")


def carregar(path: Path = ENTRADA_PADRAO) -> gpd.GeoDataFrame:
    g = gpd.read_file(path)
    g["view_date"] = pd.to_datetime(g["view_date"])
    g["publish_month"] = pd.to_datetime(g["publish_month"])
    g["chave"] = np.arange(len(g))  # gid não é único (ver auditoria)
    return g


def corrigir(geom):
    """Torna a geometria válida, mantendo apenas as partes poligonais."""
    if geom is None or geom.is_valid:
        return geom
    try:
        fixed = shapely.make_valid(geom, method="structure", keep_collapsed=False)
    except shapely.errors.GEOSException:
        fixed = geom.buffer(0)
    polys = [p for p in getattr(fixed, "geoms", [fixed]) if p.geom_type in ("Polygon", "MultiPolygon")]
    return shapely.unary_union(polys) if polys else fixed


def preparar(g: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Corrige geometrias, remove fragmentos, projeta para CRS métrico e atribui a célula de 5 km."""
    g = g.copy()
    g["geometry"] = [corrigir(x) for x in g.geometry.to_numpy()]
    g = g.to_crs(CRS_METRICO)
    # a reprojeção pode reintroduzir autointerseções mínimas (12 casos; efeito na área < 1e-7)
    g["geometry"] = [corrigir(x) for x in g.geometry.to_numpy()]
    g["area_km2"] = g.area / 1e6
    g = g[g["area_km2"] >= SLIVER_KM2].copy()
    c = g.geometry.centroid  # representação pontual inicial (limitação documentada)
    g["cx"], g["cy"] = c.x, c.y
    g["cel_i"] = np.floor(g["cx"] / CELULA_M).astype(int)
    g["cel_j"] = np.floor(g["cy"] / CELULA_M).astype(int)
    g["celula"] = g["cel_i"].astype(str) + "_" + g["cel_j"].astype(str)
    g["mes"] = g["view_date"].dt.to_period("M")
    return g


def carregar_preparado(path: Path = ENTRADA_PADRAO) -> gpd.GeoDataFrame:
    return preparar(carregar(path))


def periodo(g: pd.DataFrame, ini: str, fim: str) -> pd.DataFrame:
    """Filtra por view_date no intervalo fechado [ini, fim]."""
    return g[(g["view_date"] >= ini) & (g["view_date"] <= fim)]
