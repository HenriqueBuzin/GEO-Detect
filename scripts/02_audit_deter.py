"""Auditoria dos alertas DETER de mineração (Pará) para o recorte experimental do GEO-Detect.

Entrada: GeoJSON produzido por scripts/01_download_deter.py
Saídas (results/audit/):
    relatorio_auditoria.json   números-chave da auditoria
    campos.csv                 esquema, nulos e exemplos por campo
    anual.csv                  contagem e área por ano (todo o histórico)
    mensal_2024_2025.csv       contagem, área e células por mês no recorte
    periodos.csv               volume por período (histórico, desenvolvimento, teste)
    municipios_2024_2025.csv   distribuição por município no recorte
    fig_*.png                  gráficos e mapas

Regra anti-vazamento: o período de teste (jul–dez/2025) só entra aqui em
contagens de volume (para checar suficiência). Nenhuma sobreposição espacial
entre desenvolvimento e teste é calculada, porque isso já seria avaliar o
método de referência A no conjunto de teste.

Uso:
    python scripts/02_audit_deter.py
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import geopandas as gpd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import shapely

CRS_METRICO = "ESRI:102033"  # South America Albers Equal Area Conic (área e distância em metros)
CELULA_M = 5_000
INICIO, FIM = "2024-01-01", "2025-12-31"
DEV = ("2024-01-01", "2025-06-30")
TESTE = ("2025-07-01", "2025-12-31")
SLIVER_KM2 = 0.001  # 0,1 ha: fragmento de recorte municipal, não um alerta
ORCAMENTOS = (0.05, 0.10, 0.20)


def carregar(path: Path) -> gpd.GeoDataFrame:
    g = gpd.read_file(path)
    g["view_date"] = pd.to_datetime(g["view_date"])
    g["publish_month"] = pd.to_datetime(g["publish_month"])
    g["chave"] = np.arange(len(g))  # gid não é único (ver relatório)
    return g


def tabela_campos(g: gpd.GeoDataFrame) -> pd.DataFrame:
    linhas = []
    for c in g.columns:
        if c in ("geometry", "chave"):
            continue
        s = g[c]
        exemplo = s.dropna().iloc[0] if s.notna().any() else None
        linhas.append(
            {
                "campo": c,
                "tipo": str(s.dtype),
                "nulos": int(s.isna().sum()),
                "pct_nulos": round(100 * s.isna().mean(), 2),
                "valores_distintos": int(s.nunique()),
                "exemplo": str(exemplo),
            }
        )
    return pd.DataFrame(linhas)


def qualidade(g: gpd.GeoDataFrame, gm: gpd.GeoDataFrame) -> dict:
    invalidas = ~g.is_valid
    motivos = (
        pd.Series(shapely.is_valid_reason(g.geometry[invalidas].to_numpy()))
        .str.split("[", n=1).str[0].str.strip().value_counts().to_dict()
    )
    area = gm.area / 1e6
    dup_gid = g[g["gid"].duplicated(keep=False)]
    defasagem = (
        g["publish_month"].dt.to_period("M") - g["view_date"].dt.to_period("M")
    ).apply(lambda x: x.n)
    return {
        "registros": int(len(g)),
        "gid_repetidos": int(g["gid"].duplicated().sum()),
        "gid_repetidos_com_datas_distintas": int(dup_gid.groupby("gid")["view_date"].nunique().gt(1).sum()),
        "id_repetidos": int(g["id"].duplicated().sum()),
        "geometrias_identicas_repetidas": int(g.geometry.to_wkb().duplicated().sum()),
        "geometrias_invalidas": int(invalidas.sum()),
        "motivos_invalidade": motivos,
        "geometrias_vazias": int(g.geometry.is_empty.sum()),
        "fragmentos_menores_que_0_1ha": int((area < SLIVER_KM2).sum()),
        "area_km2_descricao": {k: round(float(v), 4) for k, v in area.describe().items()},
        "defasagem_publish_month_menos_view_date_meses": {int(k): int(v) for k, v in defasagem.value_counts().sort_index().items()},
        "municipios_grafias_distintas": int(g["municipality"].nunique()),
        "municipios_normalizados": int(g["municipality"].str.lower().nunique()),
        "gid_sufixo_hist_por_ano": g.assign(h=g["gid"].str.endswith("_hist"))
        .groupby(g["view_date"].dt.year)["h"].mean().round(3).to_dict(),
    }


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
    """Corrige geometrias, remove fragmentos e projeta para CRS métrico."""
    g = g.copy()
    g["geometry"] = [corrigir(x) for x in g.geometry.to_numpy()]
    g = g.to_crs(CRS_METRICO)
    g["area_km2"] = g.area / 1e6
    g = g[g["area_km2"] >= SLIVER_KM2].copy()
    c = g.geometry.centroid  # representação pontual inicial (limitação documentada)
    g["cx"], g["cy"] = c.x, c.y
    g["cel_i"] = np.floor(g["cx"] / CELULA_M).astype(int)
    g["cel_j"] = np.floor(g["cy"] / CELULA_M).astype(int)
    g["celula"] = g["cel_i"].astype(str) + "_" + g["cel_j"].astype(str)
    g["mes"] = g["view_date"].dt.to_period("M")
    return g


def periodo(g: pd.DataFrame, ini: str, fim: str) -> pd.DataFrame:
    return g[(g["view_date"] >= ini) & (g["view_date"] <= fim)]


def distancia_vizinho_mais_proximo(g: pd.DataFrame) -> np.ndarray:
    """Distância (km) de cada centroide ao centroide mais próximo (força bruta em blocos)."""
    xy = g[["cx", "cy"]].to_numpy()
    out = np.empty(len(xy))
    for i in range(0, len(xy), 500):
        bloco = xy[i : i + 500]
        d = np.sqrt(((bloco[:, None, :] - xy[None, :, :]) ** 2).sum(-1))
        d[np.arange(len(bloco)), np.arange(i, i + len(bloco))] = np.inf
        out[i : i + 500] = d.min(1)
    return out / 1000


def celulas_estado(limite: gpd.GeoDataFrame) -> int:
    """Número de células 5 km cujo centro está no Pará (tamanho do universo elegível ingênuo)."""
    lim = limite.to_crs(CRS_METRICO)
    xmin, ymin, xmax, ymax = lim.total_bounds
    xs = np.arange(np.floor(xmin / CELULA_M), np.ceil(xmax / CELULA_M)) * CELULA_M + CELULA_M / 2
    ys = np.arange(np.floor(ymin / CELULA_M), np.ceil(ymax / CELULA_M)) * CELULA_M + CELULA_M / 2
    X, Y = np.meshgrid(xs, ys)
    pts = shapely.points(X.ravel(), Y.ravel())
    return int(shapely.contains(lim.geometry.union_all(), pts).sum())


def universo_vizinhanca(hist: pd.DataFrame, rec: pd.DataFrame, raios_celulas=(0, 2, 4)) -> dict:
    """Universo elegível = células a até r células (Chebyshev) de alguma célula com alerta pré-2024.

    Usa apenas o histórico anterior ao recorte, portanto não vaza informação futura.
    Reporta o tamanho do universo e a fração das células com alerta em 2024–2025 que ele contém.
    """
    base = set(zip(hist["cel_i"], hist["cel_j"]))
    alvo = set(zip(rec["cel_i"], rec["cel_j"]))
    out = {}
    for r in raios_celulas:
        uni = {(i + di, j + dj) for i, j in base for di in range(-r, r + 1) for dj in range(-r, r + 1)}
        out[f"raio_{r * CELULA_M // 1000}km"] = {
            "celulas": len(uni),
            "pct_celulas_alerta_2024_2025_contidas": round(100 * len(alvo & uni) / len(alvo), 1),
            "orcamentos_em_celulas": {f"{int(b*100)}%": int(round(b * len(uni))) for b in ORCAMENTOS},
        }
    return out


def figuras(g: gpd.GeoDataFrame, rec: gpd.GeoDataFrame, mensal: pd.DataFrame, anual: pd.DataFrame,
            limite: gpd.GeoDataFrame, nn: np.ndarray, out: Path) -> None:
    plt.rcParams.update({"font.size": 10, "axes.spines.top": False, "axes.spines.right": False})
    azul, laranja, cinza = "#2a6f97", "#e07a1f", "#9aa5b1"

    # 1. série anual
    fig, ax = plt.subplots(figsize=(8, 3.6))
    cores = [azul if a in (2024, 2025) else cinza for a in anual["ano"]]
    ax.bar(anual["ano"].astype(str), anual["alertas"], color=cores)
    for x, y in zip(anual["ano"].astype(str), anual["alertas"]):
        ax.text(x, y, str(y), ha="center", va="bottom", fontsize=8)
    ax.set_title("Alertas DETER de mineração no Pará por ano (recorte destacado)")
    ax.set_ylabel("alertas")
    fig.tight_layout(); fig.savefig(out / "fig_anual.png", dpi=160); plt.close(fig)

    # 2. série mensal 2024–2025 com divisão dev/teste
    fig, ax = plt.subplots(figsize=(10, 3.8))
    m = mensal.copy()
    cor = [laranja if p >= pd.Period(TESTE[0], "M") else azul for p in m["mes_p"]]
    ax.bar(m["mes"], m["alertas"], color=cor)
    ax.set_xticks(range(len(m))); ax.set_xticklabels(m["mes"], rotation=90, fontsize=8)
    ax.set_ylabel("alertas")
    ax.set_title("Alertas mensais de mineração — Pará (azul: desenvolvimento; laranja: teste)")
    fig.tight_layout(); fig.savefig(out / "fig_mensal_2024_2025.png", dpi=160); plt.close(fig)

    # 3. mapa: centroides no Pará + zoom no núcleo
    lim = limite.to_crs(CRS_METRICO)
    fig, axs = plt.subplots(1, 2, figsize=(12, 6), gridspec_kw={"width_ratios": [1.1, 1]})
    for ax in axs:
        lim.boundary.plot(ax=ax, color="#555", linewidth=0.6)
        hist = g[g["view_date"] < INICIO]
        ax.scatter(hist["cx"], hist["cy"], s=2, c=cinza, alpha=0.4, label="2016–2023")
        d = periodo(rec, *DEV); t = periodo(rec, *TESTE)
        ax.scatter(d["cx"], d["cy"], s=5, c=azul, alpha=0.8, label="dev 2024-01→2025-06")
        ax.scatter(t["cx"], t["cy"], s=5, c=laranja, alpha=0.9, label="teste 2025-07→12")
        ax.set_xticks([]); ax.set_yticks([]); ax.set_aspect("equal")
    axs[0].set_title("Pará — centroides dos alertas de mineração")
    axs[0].legend(loc="lower left", markerscale=3, fontsize=8, frameon=False)
    x0, y0 = rec["cx"].quantile(0.02), rec["cy"].quantile(0.02)
    x1, y1 = rec["cx"].quantile(0.98), rec["cy"].quantile(0.98)
    pad = 30_000
    axs[1].set_xlim(x0 - pad, x1 + pad); axs[1].set_ylim(y0 - pad, y1 + pad)
    axs[1].set_title("Zoom: 96% central dos alertas 2024–2025")
    fig.tight_layout(); fig.savefig(out / "fig_mapa_alertas.png", dpi=160); plt.close(fig)

    # 4. densidade por célula 5 km (2024–2025)
    cont = rec.groupby(["cel_i", "cel_j"]).size().reset_index(name="n")
    fig, ax = plt.subplots(figsize=(7, 6))
    lim.boundary.plot(ax=ax, color="#555", linewidth=0.6)
    sc = ax.scatter((cont["cel_i"] + 0.5) * CELULA_M, (cont["cel_j"] + 0.5) * CELULA_M,
                    c=cont["n"], s=8, marker="s", cmap="viridis", norm=matplotlib.colors.LogNorm())
    fig.colorbar(sc, ax=ax, shrink=0.7, label="alertas por célula 5×5 km (log)")
    ax.set_xticks([]); ax.set_yticks([]); ax.set_aspect("equal")
    ax.set_title("Células 5×5 km com alertas de mineração, 2024–2025")
    fig.tight_layout(); fig.savefig(out / "fig_celulas_5km.png", dpi=160); plt.close(fig)

    # 5. distância ao vizinho mais próximo (desenvolvimento) — apoia o limiar do grafo
    fig, ax = plt.subplots(figsize=(7, 3.6))
    ax.hist(np.clip(nn, 0, 50), bins=50, color=azul)
    for q, ls in ((0.5, "--"), (0.9, ":")):
        v = np.quantile(nn, q)
        ax.axvline(v, color="k", ls=ls, lw=1, label=f"P{int(q*100)} = {v:.1f} km")
    ax.set_xlabel("distância ao alerta mais próximo (km, truncada em 50)")
    ax.set_ylabel("alertas"); ax.legend(frameon=False)
    ax.set_title("Vizinho mais próximo — período de desenvolvimento")
    fig.tight_layout(); fig.savefig(out / "fig_vizinho_mais_proximo.png", dpi=160); plt.close(fig)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--entrada", default="data/raw/deter_amz_mineracao_pa.geojson", type=Path)
    ap.add_argument("--limite", default="data/raw/limite_pa_ibge.geojson", type=Path)
    ap.add_argument("--saida", default="results/audit", type=Path)
    args = ap.parse_args()
    args.saida.mkdir(parents=True, exist_ok=True)

    g_raw = carregar(args.entrada)
    limite = gpd.read_file(args.limite)
    meta_dl = Path(args.entrada).with_name("download_metadata.json")

    tabela_campos(g_raw).to_csv(args.saida / "campos.csv", index=False)
    q_total = qualidade(g_raw, g_raw.to_crs(CRS_METRICO))
    rec_raw = periodo(g_raw, INICIO, FIM)
    q_rec = qualidade(rec_raw, rec_raw.to_crs(CRS_METRICO))

    g = preparar(g_raw)
    rec = periodo(g, INICIO, FIM)
    hist = g[g["view_date"] < INICIO]
    dev, teste = periodo(g, *DEV), periodo(g, *TESTE)

    # anual (todo o histórico)
    anual = (
        g.groupby(g["view_date"].dt.year)
        .agg(alertas=("chave", "size"), area_km2=("area_km2", "sum"), celulas_5km=("celula", "nunique"))
        .reset_index(names="ano")
    )
    anual["area_km2"] = anual["area_km2"].round(2)
    anual.to_csv(args.saida / "anual.csv", index=False)

    # mensal (recorte), incluindo meses sem alerta
    meses = pd.period_range(INICIO, FIM, freq="M")
    mensal = (
        rec.groupby("mes")
        .agg(alertas=("chave", "size"), area_km2=("area_km2", "sum"), celulas_5km=("celula", "nunique"),
             datas_imagem=("view_date", "nunique"), municipios=("municipality", "nunique"))
        .reindex(meses, fill_value=0)
        .rename_axis("mes_p").reset_index()
    )
    mensal["area_km2"] = mensal["area_km2"].round(2)
    mensal["mes"] = mensal["mes_p"].astype(str)
    mensal["periodo"] = np.where(mensal["mes_p"] >= pd.Period(TESTE[0], "M"), "teste", "desenvolvimento")
    mensal.drop(columns="mes_p").to_csv(args.saida / "mensal_2024_2025.csv", index=False)

    # municípios (recorte)
    mun = (
        rec.assign(mun=rec["municipality"].str.title())
        .groupby("mun").agg(alertas=("chave", "size"), area_km2=("area_km2", "sum"), celulas_5km=("celula", "nunique"))
        .sort_values("alertas", ascending=False)
    )
    mun["pct_alertas"] = (100 * mun["alertas"] / mun["alertas"].sum()).round(1)
    mun["pct_acumulado"] = mun["pct_alertas"].cumsum().round(1)
    mun["area_km2"] = mun["area_km2"].round(2)
    mun.to_csv(args.saida / "municipios_2024_2025.csv")

    # períodos
    def resumo(df: pd.DataFrame, nome: str, ini: str, fim: str) -> dict:
        return {
            "periodo": nome, "inicio": ini, "fim": fim, "alertas": int(len(df)),
            "area_km2": round(float(df["area_km2"].sum()), 2),
            "celulas_5km": int(df["celula"].nunique()),
            "meses_com_alerta": int(df["mes"].nunique()),
            "datas_de_imagem": int(df["view_date"].nunique()),
            "pct_em_uc": round(100 * float(df["uc"].notna().mean()), 1) if len(df) else None,
        }

    periodos = pd.DataFrame([
        resumo(hist, "historico_pre_recorte", str(g["view_date"].min().date()), "2023-12-31"),
        resumo(dev, "desenvolvimento", *DEV),
        resumo(teste, "teste", *TESTE),
    ])
    periodos.to_csv(args.saida / "periodos.csv", index=False)

    # concentração espacial no recorte
    por_cel = rec.groupby("celula").size().sort_values(ascending=False)
    acum = por_cel.cumsum() / por_cel.sum()
    n_universo = celulas_estado(limite)

    # persistência DENTRO do desenvolvimento: 2025-S1 versus o que veio antes (sem tocar no teste)
    s1_2025 = periodo(g, "2025-01-01", "2025-06-30")
    antes = g[g["view_date"] < "2025-01-01"]
    cel_s1 = set(s1_2025["celula"])
    persist = {
        "janela_alvo": "2025-01-01 a 2025-06-30 (dentro do desenvolvimento)",
        "celulas_alvo": len(cel_s1),
        "pct_com_alerta_em_2024": round(100 * len(cel_s1 & set(periodo(g, "2024-01-01", "2024-12-31")["celula"])) / max(len(cel_s1), 1), 1),
        "pct_com_alerta_em_qualquer_ano_anterior": round(100 * len(cel_s1 & set(antes["celula"])) / max(len(cel_s1), 1), 1),
        "nota": "Indicador descritivo de recorrência; o período de teste não foi usado.",
    }

    nn = distancia_vizinho_mais_proximo(dev)

    # sazonalidade: proporção de alertas por mês-do-ano no histórico completo
    saz = g.groupby(g["view_date"].dt.month).size()
    saz = (100 * saz / saz.sum()).round(1)

    relatorio = {
        "download": json.loads(meta_dl.read_text(encoding="utf-8")) if meta_dl.exists() else None,
        "crs_original": str(g_raw.crs),
        "crs_analise": CRS_METRICO,
        "tamanho_celula_m": CELULA_M,
        "qualidade_historico_completo": q_total,
        "qualidade_recorte_2024_2025": q_rec,
        "tratamento": {
            "geometrias": "shapely.make_valid(method='structure'), partes poligonais; fallback buffer(0)",
            "fragmentos_removidos_lt_0_1ha_total": int(len(g_raw) - len(g)),
            "chave": "índice próprio (gid não é único)",
            "atribuicao_celula": "centroide do polígono",
        },
        "periodos": periodos.to_dict("records"),
        "recorte_2024_2025": {
            "alertas": int(len(rec)),
            "meses_sem_alerta": [str(m) for m in mensal.loc[mensal["alertas"] == 0, "mes"]],
            "celulas_5km_com_alerta": int(por_cel.size),
            "celulas_para_50pct_dos_alertas": int((acum < 0.5).sum() + 1),
            "celulas_para_80pct_dos_alertas": int((acum < 0.8).sum() + 1),
            "municipios": int(mun.shape[0]),
            "top3_municipios_pct": round(float(mun["pct_alertas"].head(3).sum()), 1),
            "top_municipios": mun.head(5)["alertas"].to_dict(),
        },
        "universo_elegivel": {
            "celulas_5km_no_para": n_universo,
            "orcamentos_em_celulas": {f"{int(b*100)}%": int(round(b * n_universo)) for b in ORCAMENTOS},
            "celulas_com_alerta_2024_2025_pct_do_estado": round(100 * por_cel.size / n_universo, 3),
            "alternativa_vizinhanca_historica": universo_vizinhanca(hist, rec),
        },
        "persistencia_dentro_do_desenvolvimento": persist,
        "vizinho_mais_proximo_dev_km": {f"P{p}": round(float(np.quantile(nn, p / 100)), 2) for p in (10, 25, 50, 75, 90, 95)},
        "sazonalidade_pct_por_mes_historico": {int(k): float(v) for k, v in saz.items()},
    }
    (args.saida / "relatorio_auditoria.json").write_text(
        json.dumps(relatorio, indent=2, ensure_ascii=False, default=str), encoding="utf-8"
    )

    figuras(g, rec, mensal, anual, limite, nn, args.saida)
    print(json.dumps({k: relatorio[k] for k in (
        "periodos", "recorte_2024_2025", "universo_elegivel",
        "persistencia_dentro_do_desenvolvimento", "vizinho_mais_proximo_dev_km",
        "qualidade_recorte_2024_2025", "tratamento")}, indent=2, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
