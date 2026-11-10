"""H3 resolução 15: viabilidade computacional e experimento EXPLORATÓRIO controlado (só desenvolvimento).

Registro: o pedido original era testar o H3 r15. Antes de qualquer execução, a escala estimada
(~10¹¹ células) motivou restringir a curva de resolução a r6–r10 (script 08). Este script responde
ao pedido de r15 de forma controlada, sem enumerar o Pará.

Etapas
------
1. Viabilidade (analítica + benchmark): células, memória e tempo para enumerar o universo em r15.
   Se a estimativa exceder os limites abaixo, a enumeração completa NÃO é executada.
2. Fragmentação, numa janela pequena (enumerada de verdade, com limite de células): o que o r15 faz
   com um polígono DETER. Compara a precisão do r15 com a precisão geométrica dos próprios polígonos.
3. Experimento r15 amostrado. Uma célula r15 tem ~0,9 m², ou seja, é praticamente um ponto. Por isso,
   a ordenação de todas as células do universo é estimada sorteando N pontos uniformes no universo
   (cada ponto representa sua célula r15, cuja pontuação é calculada no centro da célula).
   Modelos comparados (janela de 24 meses antes do corte, como nos demais scripts):
       r15_centroide  nº de centroides de alertas passados na mesma célula r15
       r15_poligono   nº de polígonos passados que contêm o centro da célula (pegada)
       r15_anel1      r15_poligono + 0,5 · média de r15_poligono nos 6 vizinhos imediatos (a ~0,6 m)
       r15_raio1km    nº de centroides de alertas passados a até 1 km do centro da célula
       r15_raio3km    idem, 3 km
       r7_raio1km / r7_raio3km   os mesmos raios no centro das células r7 (controle de resolução)
   Os raios de 1 km e 3 km são fixados a priori (sem ajuste).
   Métricas: recall de alertas (centroide do alerta-alvo) e recall de área (fração da área dos
   polígonos-alvo coberta, estimada por pontos sorteados dentro de cada polígono-alvo).

Somente origens de desenvolvimento. O teste independente de 2026 NÃO é lido.

Limites de recursos (explícitos): ver LIMITES. O pico de memória Python é medido com tracemalloc.

Saídas (results/r15/): viabilidade.json, fragmentacao.json, experimento_por_origem.csv,
    experimento_resumo.csv, fig_r15.png, RELATORIO.md (escrito à parte)

Uso:
    python scripts/09_r15_experiment.py
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import tracemalloc
from pathlib import Path

import h3
import h3.api.numpy_int as hn
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import shapely
from pyproj import Transformer
from scipy.spatial import cKDTree

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from geodetect.avaliacao import alvo, corte, disponiveis, origens_dev, universo_quadrados  # noqa: E402
from geodetect.dados import CELULA_M, CRS_METRICO, DEV, carregar_preparado  # noqa: E402
from geodetect.grades import GradeH3  # noqa: E402

LIMITES = {
    "memoria_gb": 2.0,              # teto para qualquer estrutura em memória
    "celulas_enumeradas_max": 5e6,  # teto de células r15 enumeradas de uma vez
    "pontos_amostra_max": 1_000_000,
    "tempo_enumeracao_h_max": 1.0,
}
N_PONTOS = 400_000        # pontos uniformes por origem (representam células r15)
PONTOS_POR_ALVO = 25      # pontos por polígono-alvo, para o recall de área
SEMENTES = (0, 1)         # duas amostras independentes para medir o erro de Monte Carlo
FRACOES = (0.01, 0.02, 0.05)
JANELA = 24
RAIOS_M = (1000, 3000)
W_ANEL = 0.5
JANELA_DEMO_M = 400
_LL = Transformer.from_crs(CRS_METRICO, "EPSG:4326", always_xy=True)
_M = Transformer.from_crs("EPSG:4326", CRS_METRICO, always_xy=True)


def para_ll(x, y):
    lon, lat = _LL.transform(np.asarray(x, float), np.asarray(y, float))
    return np.asarray(lat), np.asarray(lon)


def celulas_int(lat, lon, res) -> np.ndarray:
    return np.array([h3.str_to_int(h3.latlng_to_cell(a, b, res)) for a, b in zip(lat, lon)], dtype=np.uint64)


def centros_m(cel: np.ndarray):
    ll = np.array([h3.cell_to_latlng(h3.int_to_str(int(c))) for c in cel])
    x, y = _M.transform(ll[:, 1], ll[:, 0])
    return np.asarray(x), np.asarray(y)


# ---------------------------------------------------------------- etapa 1
def viabilidade(g: pd.DataFrame, quad_u: list[str]) -> dict:
    area_u_km2 = 25.0 * len(quad_u)
    out = {"area_universo_km2": area_u_km2, "limites": LIMITES, "por_resolucao": {}}
    # benchmark de enumeração em caixas pequenas (r15)
    x, y = g.geometry.iloc[0].centroid.x, g.geometry.iloc[0].centroid.y
    taxas = []
    for lado in (100, 200, 400):
        caixa = shapely.box(x, y, x + lado, y + lado)
        ll = shapely.transform(caixa, lambda xy: np.column_stack(_LL.transform(xy[:, 0], xy[:, 1])))
        t = time.perf_counter()
        n = len(hn.h3shape_to_cells(h3.geo_to_h3shape(ll.__geo_interface__), 15))
        taxas.append(n / (time.perf_counter() - t))
    taxa = float(np.median(taxas))
    area_alertas = float(g["area_km2"].sum())
    for res in (7, 10, 12, 15):
        a_m2 = h3.average_hexagon_area(res, unit="m^2")
        n = area_u_km2 * 1e6 / a_m2
        out["por_resolucao"][f"r{res}"] = {
            "area_media_celula_m2": a_m2, "aresta_m": h3.average_hexagon_edge_length(res, unit="m"),
            "celulas_universo": n, "memoria_ids_uint64_gb": n * 8 / 1e9,
            "memoria_ids_e_6_vizinhos_gb": n * 8 * 7 / 1e9,
            "celulas_dentro_dos_poligonos_dev": area_alertas * 1e6 / a_m2,
            "celulas_por_alerta_mediano": float(g["area_km2"].median() * 1e6 / a_m2),
        }
    r15 = out["por_resolucao"]["r15"]
    r15["tempo_enumeracao_h_estimado"] = r15["celulas_universo"] / taxa / 3600
    out["taxa_enumeracao_r15_celulas_por_s"] = taxa
    viavel = (r15["memoria_ids_uint64_gb"] <= LIMITES["memoria_gb"]
              and r15["celulas_universo"] <= LIMITES["celulas_enumeradas_max"]
              and r15["tempo_enumeracao_h_estimado"] <= LIMITES["tempo_enumeracao_h_max"])
    out["enumeracao_completa_r15_viavel"] = bool(viavel)
    out["decisao"] = ("executar enumeração completa" if viavel else
                      "NÃO enumerar o universo em r15; usar janela pequena (etapa 2) e amostragem (etapa 3)")
    # precisão geométrica do dado
    segs = []
    for geom in g.geometry.iloc[::10]:
        for p in getattr(geom, "geoms", [geom]):
            c = np.asarray(p.exterior.coords)
            segs.append(np.hypot(*np.diff(c, axis=0).T))
    s = np.concatenate(segs)
    s = s[s > 0]
    out["precisao_poligonos_deter"] = {"segmento_m_P5": float(np.percentile(s, 5)),
                                       "segmento_m_mediana": float(np.median(s)),
                                       "pixel_sensores_m": "AWFI ~64 m; WFI ~55 m; AWiFS ~56 m"}
    return out


# ---------------------------------------------------------------- etapa 2
def fragmentacao(g: pd.DataFrame) -> dict:
    alvo_demo = g[g["view_date"] >= DEV[0]].sort_values("area_km2").iloc[len(g[g["view_date"] >= DEV[0]]) // 2]
    poly = alvo_demo.geometry
    cx, cy = poly.centroid.x, poly.centroid.y
    h = JANELA_DEMO_M / 2
    caixa = shapely.box(cx - h, cy - h, cx + h, cy + h)
    ll = shapely.transform(caixa, lambda xy: np.column_stack(_LL.transform(xy[:, 0], xy[:, 1])))
    est = (JANELA_DEMO_M ** 2) / h3.average_hexagon_area(15, unit="m^2")
    if est > LIMITES["celulas_enumeradas_max"]:
        return {"executado": False, "motivo": f"estimativa {est:.0f} > limite"}
    cel = hn.h3shape_to_cells(h3.geo_to_h3shape(ll.__geo_interface__), 15)
    x, y = centros_m(cel)
    dentro15 = shapely.contains_xy(poly, x, y)
    out = {"executado": True, "alerta_area_ha": float(alvo_demo["area_km2"] * 100),
           "janela_m": JANELA_DEMO_M, "celulas_r15_na_janela": int(len(cel)),
           "celulas_r15_dentro_do_alerta": int(dentro15.sum()),
           "area_alerta_estimada_por_r15_ha": float(dentro15.sum() * h3.average_hexagon_area(15, unit="m^2") / 1e4)}
    # concordância com resoluções mais grossas: o estado dentro/fora muda só na borda?
    for res in (10, 11, 12):
        pais = np.array([h3.str_to_int(h3.cell_to_parent(h3.int_to_str(int(c)), res)) for c in cel], dtype=np.uint64)
        up, inv = np.unique(pais, return_inverse=True)
        px, py = centros_m(up)
        dentro_pai = shapely.contains_xy(poly, px, py)[inv]
        out[f"pct_celulas_r15_iguais_ao_pai_r{res}"] = float(100 * (dentro_pai == dentro15).mean())
        out[f"aresta_r{res}_m"] = h3.average_hexagon_edge_length(res, unit="m")
    out["celulas_r15_por_pixel_64m"] = 64 * 64 / h3.average_hexagon_area(15, unit="m^2")
    # figura da janela
    fig, ax = plt.subplots(figsize=(5, 5))
    ax.scatter(x[~dentro15], y[~dentro15], s=0.05, c="#d0d7de")
    ax.scatter(x[dentro15], y[dentro15], s=0.05, c="#e07a1f")
    for p in getattr(poly, "geoms", [poly]):
        ax.plot(*p.exterior.xy, color="k", lw=0.8)
    ax.set_aspect("equal"); ax.set_xticks([]); ax.set_yticks([])
    ax.set_title(f"{len(cel):,} células r15 numa janela de {JANELA_DEMO_M} m\n"
                 f"{int(dentro15.sum()):,} dentro de um alerta de {out['alerta_area_ha']:.1f} ha", fontsize=9)
    out["_fig"] = fig
    return out


# ---------------------------------------------------------------- etapa 3
def limiar_e_prob(amostra: np.ndarray, f: float):
    """Limiar s* e probabilidade de seleção no empate, estimados da amostra do universo."""
    s = np.sort(amostra)[::-1]
    k = f * len(s)
    s_star = s[min(int(np.ceil(k)) - 1, len(s) - 1)]
    p_gt = (amostra > s_star).mean()
    p_eq = (amostra == s_star).mean()
    p_emp = (f - p_gt) / p_eq if p_eq > 0 else 0.0
    return s_star, float(np.clip(p_emp, 0, 1))


def prob_captura(score: np.ndarray, s_star: float, p_emp: float) -> np.ndarray:
    return np.where(score > s_star, 1.0, np.where(score == s_star, p_emp, 0.0))


def pontos_em_quadrados(quad: list[str], n: int, rng) -> tuple[np.ndarray, np.ndarray]:
    ij = np.array([q.split("_") for q in quad], dtype=int)
    idx = rng.integers(0, len(ij), n)
    return (ij[idx, 0] + rng.random(n)) * CELULA_M, (ij[idx, 1] + rng.random(n)) * CELULA_M


def pontos_em_poligonos(polys, m: int, rng):
    xs, ys, dono = [], [], []
    for i, p in enumerate(polys):
        x0, y0, x1, y1 = p.bounds
        acc = 0
        while acc < m:
            px = rng.uniform(x0, x1, 4 * m); py = rng.uniform(y0, y1, 4 * m)
            ok = shapely.contains_xy(p, px, py)
            px, py = px[ok][: m - acc], py[ok][: m - acc]
            xs.append(px); ys.append(py); dono.append(np.full(len(px), i)); acc += len(px)
    return np.concatenate(xs), np.concatenate(ys), np.concatenate(dono)


def scores_r15(x, y, hist: pd.DataFrame, arvore_poly, polys, kd, cent_set):
    """Pontuações r15 avaliadas no centro da célula r15 de cada ponto (x, y)."""
    lat, lon = para_ll(x, y)
    cel = celulas_int(lat, lon, 15)
    cx, cy = centros_m(cel)
    pts = shapely.points(cx, cy)
    sc = {"r15_centroide": np.isin(cel, cent_set).astype(float)}
    par = arvore_poly.query(pts, predicate="within")
    sc["r15_poligono"] = np.bincount(par[0], minlength=len(cel)).astype(float)
    # anel 1: centros dos 6 vizinhos imediatos (~0,6 m)
    viz = np.array([[h3.str_to_int(v) for v in h3.grid_ring(h3.int_to_str(int(c)), 1)] for c in cel], dtype=np.uint64)
    vx, vy = centros_m(viz.ravel())
    pv = arvore_poly.query(shapely.points(vx, vy), predicate="within")
    nv = np.bincount(pv[0], minlength=len(vx)).reshape(viz.shape).mean(1)
    sc["r15_anel1"] = sc["r15_poligono"] + W_ANEL * nv
    for r in RAIOS_M:
        sc[f"r15_raio{r // 1000}km"] = kd.query_ball_point(np.column_stack([cx, cy]), r, return_length=True).astype(float) if kd else np.zeros(len(cx))
    return sc


def scores_r7_raio(x, y, kd):
    lat, lon = para_ll(x, y)
    cel = celulas_int(lat, lon, 7)
    up, inv = np.unique(cel, return_inverse=True)
    cx, cy = centros_m(up)
    out = {}
    for r in RAIOS_M:
        v = kd.query_ball_point(np.column_stack([cx, cy]), r, return_length=True).astype(float) if kd else np.zeros(len(up))
        out[f"r7_raio{r // 1000}km"] = v[inv]
    return out, cel


def experimento(g: pd.DataFrame) -> pd.DataFrame:
    if N_PONTOS > LIMITES["pontos_amostra_max"]:
        raise SystemExit("amostra acima do limite")
    linhas = []
    for semente in SEMENTES:
        rng = np.random.default_rng(semente)
        for t in origens_dev():
            c = corte(t)
            disp = disponiveis(g, t)
            hist = disp[disp["view_date"] >= c - pd.DateOffset(months=JANELA)]
            tgt = alvo(g, t)
            u = universo_quadrados(disp["cel_i"].to_numpy(), disp["cel_j"].to_numpy())
            polys = hist.geometry.to_numpy()
            arv = shapely.STRtree(polys)
            hc = hist.geometry.centroid
            kd = cKDTree(np.column_stack([hc.x, hc.y])) if len(hist) else None
            hlat, hlon = para_ll(hc.x, hc.y)
            cent_set = celulas_int(hlat, hlon, 15)

            # universo amostrado (cada ponto = uma célula r15) e células r7 do universo (via mesma amostra)
            ux, uy = pontos_em_quadrados(u, N_PONTOS, rng)
            su = scores_r15(ux, uy, hist, arv, polys, kd, cent_set)
            s7u, _ = scores_r7_raio(ux, uy, kd)
            su |= s7u
            # alvos: centroide (recall de alertas) e pontos dentro dos polígonos (recall de área)
            tcx, tcy = tgt.geometry.centroid.x.to_numpy(), tgt.geometry.centroid.y.to_numpy()
            st = scores_r15(tcx, tcy, hist, arv, polys, kd, cent_set)
            st |= scores_r7_raio(tcx, tcy, kd)[0]
            ax_, ay_, dono = pontos_em_poligonos(tgt.geometry.to_numpy(), PONTOS_POR_ALVO, rng)
            sa = scores_r15(ax_, ay_, hist, arv, polys, kd, cent_set)
            sa |= scores_r7_raio(ax_, ay_, kd)[0]
            area_t = tgt["area_km2"].to_numpy()
            for f in FRACOES:
                for m in su:
                    s_star, p_emp = limiar_e_prob(su[m], f)
                    p_alerta = prob_captura(st[m], s_star, p_emp)
                    p_pts = prob_captura(sa[m], s_star, p_emp)
                    frac_poly = np.bincount(dono, weights=p_pts, minlength=len(tgt)) / PONTOS_POR_ALVO
                    linhas.append({"semente": semente, "origem": t.date().isoformat(), "modelo": m, "fracao": f,
                                   "recall_alertas": float(p_alerta.mean()),
                                   "recall_area": float((frac_poly * area_t).sum() / area_t.sum()),
                                   "pct_universo_score_pos": float(100 * (su[m] > 0).mean()),
                                   "alertas_alvo": len(tgt)})
            print(f"semente {semente} origem {t.date()} ok")
    return pd.DataFrame(linhas)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--saida", default="results/r15", type=Path)
    args = ap.parse_args()
    args.saida.mkdir(parents=True, exist_ok=True)

    g = carregar_preparado()
    g = g[g["view_date"] <= DEV[1]].copy()  # o teste nunca entra na memória deste script
    disp_ult = disponiveis(g, origens_dev()[-1])
    quad_u = universo_quadrados(disp_ult["cel_i"].to_numpy(), disp_ult["cel_j"].to_numpy())

    tracemalloc.start()
    t0 = time.perf_counter()
    v = viabilidade(g, quad_u)
    (args.saida / "viabilidade.json").write_text(json.dumps(v, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({k: v[k] for k in ("enumeracao_completa_r15_viavel", "decisao")}, ensure_ascii=False))

    fr = fragmentacao(g)
    fig = fr.pop("_fig", None)
    if fig is not None:
        fig.tight_layout(); fig.savefig(args.saida / "fig_fragmentacao_r15.png", dpi=200); plt.close(fig)
    (args.saida / "fragmentacao.json").write_text(json.dumps(fr, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(fr, indent=1))

    ex = experimento(g)
    _, pico = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    if pico / 1e9 > LIMITES["memoria_gb"]:
        print(f"AVISO: pico de memória {pico/1e9:.2f} GB acima do limite")
    ex.to_csv(args.saida / "experimento_por_origem.csv", index=False, float_format="%.5f")

    res = (ex.groupby(["modelo", "fracao"])
           .agg(recall_alertas=("recall_alertas", "mean"), recall_area=("recall_area", "mean"),
                pct_universo_score_pos=("pct_universo_score_pos", "mean"))
           .reset_index())
    mc = ex.groupby(["modelo", "fracao", "semente"])["recall_alertas"].mean().unstack()
    res = res.merge((mc[SEMENTES[0]] - mc[SEMENTES[1]]).abs().rename("dif_entre_sementes").reset_index(),
                    on=["modelo", "fracao"])
    res.to_csv(args.saida / "experimento_resumo.csv", index=False, float_format="%.4f")

    meta = {"tempo_total_s": round(time.perf_counter() - t0, 1), "pico_memoria_python_mb": round(pico / 2**20, 1),
            "n_pontos_por_origem": N_PONTOS, "pontos_por_alvo": PONTOS_POR_ALVO, "sementes": list(SEMENTES),
            "limites": LIMITES}
    (args.saida / "execucao.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")

    # figura
    plt.rcParams.update({"font.size": 10, "axes.spines.top": False, "axes.spines.right": False})
    ref = pd.read_csv("results/resolucao/curva_resumo.csv")
    ordem = ["r15_centroide", "r15_poligono", "r15_anel1", "r15_raio1km", "r15_raio3km", "r7_raio1km", "r7_raio3km"]
    fig, axs = plt.subplots(1, 2, figsize=(12, 4.2), sharey=True)
    for ax, met in zip(axs, ("recall_alertas", "recall_area")):
        d = res[res["fracao"] == 0.02].set_index("modelo").loc[ordem, met]
        cores = ["#c9d1d9", "#9aa5b1", "#6e7781", "#e07a1f", "#b35c00", "#2a6f97", "#1b4965"]
        ax.barh(range(len(d)), d.values, color=cores)
        ax.set_yticks(range(len(d))); ax.set_yticklabels(ordem, fontsize=8)
        r7 = ref[(ref["res"] == 7) & (ref["modelo"] == "C*") & (ref["fracao"] == 0.02)]["recall_6orig"].iloc[0]
        if met == "recall_alertas":
            ax.axvline(r7, color="k", ls="--", lw=1, label=f"r7 + vizinhos (script 08) = {r7:.3f}")
            ax.legend(frameon=False, fontsize=8, loc="lower right")
        ax.set_xlabel("recall de alertas" if met == "recall_alertas" else "recall de área")
        ax.invert_yaxis()
    fig.suptitle("H3 r15 (amostrado) — orçamento 2% da área, 6 origens de desenvolvimento (EXPLORATÓRIO)", fontsize=11)
    fig.tight_layout(); fig.savefig(args.saida / "fig_r15.png", dpi=160); plt.close(fig)

    pd.set_option("display.width", 200)
    print(res.pivot(index="modelo", columns="fracao", values="recall_alertas").loc[ordem].round(3))
    print(res[res["fracao"] == 0.02].set_index("modelo").loc[ordem].round(4))
    print(meta)


if __name__ == "__main__":
    main()
