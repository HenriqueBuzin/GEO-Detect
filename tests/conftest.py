"""Configuração dos testes. Todos os dados criados aqui são SINTÉTICOS e servem só para testar código."""

import importlib.util
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
import shapely

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from geodetect.dados import CRS_METRICO  # noqa: E402

# ponto de referência na região do Tapajós, no CRS métrico
X0, Y0 = 400_000.0, 2_850_000.0


def carregar_script(nome: str):
    spec = importlib.util.spec_from_file_location(nome, RAIZ / "scripts" / f"{nome}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def alertas_sinteticos() -> gpd.GeoDataFrame:
    """Alertas SINTÉTICOS (não são dados do INPE): polígonos simples, multipolígono e um que cruza divisas."""
    geoms = [
        shapely.box(X0 + 100, Y0 + 100, X0 + 400, Y0 + 400),                      # pequeno, dentro de uma célula
        shapely.box(X0 + 4_800, Y0 + 4_800, X0 + 5_300, Y0 + 5_300),               # cruza 4 quadrados de 5 km
        shapely.MultiPolygon([shapely.box(X0 + 1_000, Y0 + 1_000, X0 + 1_100, Y0 + 1_100),
                              shapely.box(X0 + 1_150, Y0 + 1_000, X0 + 1_250, Y0 + 1_100),
                              shapely.box(X0 + 1_300, Y0 + 1_000, X0 + 1_400, Y0 + 1_100)]),  # partes na mesma célula
        shapely.Polygon([(X0 + 9_000, Y0), (X0 + 12_000, Y0 + 300), (X0 + 9_100, Y0 + 2_500)]),  # alongado
    ]
    g = gpd.GeoDataFrame({
        "chave": np.arange(len(geoms)),
        "view_date": pd.to_datetime(["2023-05-10", "2023-11-02", "2024-02-15", "2024-03-20"]),
    }, geometry=geoms, crs=CRS_METRICO)
    g["area_km2"] = g.area / 1e6
    return g
