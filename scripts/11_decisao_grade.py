"""Análise de decisão da grade principal: H3 r7 × quadrado de 2,5 km — EXPLORATÓRIA, só desenvolvimento.

Não é um novo teste confirmatório. O teste independente de 2026 já foi usado (protocolo congelado em 41c29b4,
resultado em 35ac514) e NÃO é lido aqui: os dados são cortados em DEV[1] = 2025-06-30 logo após a carga.

Perguntas (todas descritivas, nas 6 origens de desenvolvimento 2024-01 → 2025-04):
  1. Estabilidade espacial: quanto o recall, as pontuações e as áreas selecionadas mudam quando a ORIGEM da
     grade é deslocada? O H3 tem estrutura geográfica fixa e não admite deslocamento equivalente, por isso
     ele entra como uma única realização. Os deslocamentos são feitos em grades planas no CRS métrico:
       quadrado_2.5km        lado 2,5 km, vizinhança de Moore (8)    — o controle do protocolo
       quadrado_2.5km_vn     lado 2,5 km, von Neumann (4)            — ablação de vizinhança
       quadrado_aream_h3     lado √(área média do H3 r7), Moore (8)  — remove o resíduo de área (~10%)
       hex_plano_6.25km2     hexágono plano (Albers) de 6,25 km², 6  — forma pura, área do quadrado
       hex_plano_aream_h3    hexágono plano com a área média do H3 r7 — forma pura, área do H3
     Os hexágonos planos NÃO são o H3: servem para separar o efeito da forma do efeito do posicionamento.
  2. Bordas: probabilidade de captura dos alertas-alvo em função da distância do centroide à borda da célula.
  3. Estrutura: células elegíveis, relações de vizinhança e área da vizinhança.
  4. Custo (--bench): tempo e pico de memória do pipeline H3 r7 × quadrado 2,5 km (classes de geodetect/).

O pipeline (pontuações A e C, orçamento em km², empate pela expectativa, universo por centro de célula nos
quadrados de 5 km) é o mesmo de scripts/07_final_evaluation.py. Com deslocamento zero, os resultados do
quadrado de 2,5 km e do H3 r7 reproduzem results/avaliacao_final/dev/por_origem.csv (verificado na execução).

Saídas: results/decisao_grade/
Uso:
    python scripts/11_decisao_grade.py            # análise de deslocamentos e bordas
    python scripts/11_decisao_grade.py --bench    # benchmark de custo (5 repetições por grade, subprocessos)
"""

from __future__ import annotations

import argparse
import json
import platform
import resource
import subprocess
import sys
import time
import tracemalloc
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import h3  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import shapely  # noqa: E402

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
from geodetect.avaliacao import alvo, disponiveis, origens_dev, selecao_deterministica, universo_quadrados  # noqa: E402
from geodetect.dados import CELULA_M, DEV, carregar_preparado  # noqa: E402
from geodetect.grades import _PARA_LONLAT, GradeH3, GradeQuadrada  # noqa: E402
from geodetect.modelos import k_orcamento, pontuacoes, prob_selecao  # noqa: E402

SAIDA = RAIZ / "results" / "decisao_grade"
PROTOCOLO = json.loads((RAIZ / "protocolo" / "protocolo_avaliacao_final.json").read_text(encoding="utf-8"))
W = PROTOCOLO["modelos"]["h3_r7_C"]["w"]  # 0,5, congelado; nada é reajustado aqui
MODELOS = {"A": None, "C": W}
ORCAMENTOS = tuple(PROTOCOLO["orcamentos"])
PRIMARIO = PROTOCOLO["orcamento_primario"]
N_DESLOC, SEMENTE, PIXEL_M = 16, 2027, 500
BASE = 500_000  # codificação inteira de (i, j): (i + BASE) * 1e6 + (j + BASE)


def cod(i, j) -> np.ndarray:
    return (np.asarray(i, dtype=np.int64) + BASE) * 1_000_000 + (np.asarray(j, dtype=np.int64) + BASE)


def quad_int(ids) -> np.ndarray:
    ij = np.array([s.split("_") for s in ids], dtype=np.int64).reshape(-1, 2)
    return cod(ij[:, 0], ij[:, 1])


def quad_de(x, y) -> np.ndarray:
    return cod(np.floor(np.asarray(x) / CELULA_M), np.floor(np.asarray(y) / CELULA_M))


# ---------------------------------------------------------------------------------------------------------------
# Grades planas deslocáveis e adaptador do H3. Interface comum:
#   celula_de(x, y), centros_candidatos(bbox), vizinhos(cel), area(cel), dist_borda(x, y)
# ---------------------------------------------------------------------------------------------------------------
class Quadrada:
    forma = "quadrado"

    def __init__(self, lado_m: float, dx: float = 0.0, dy: float = 0.0, viz: str = "moore"):
        self.L, self.dx, self.dy, self.viz = float(lado_m), float(dx), float(dy), viz
        self.area_km2 = self.L ** 2 / 1e6
        d = [(a, b) for a in (-1, 0, 1) for b in (-1, 0, 1) if (a, b) != (0, 0)]
        self.desloc_viz = d if viz == "moore" else [(1, 0), (-1, 0), (0, 1), (0, -1)]

    def _ij(self, x, y):
        return np.floor((np.asarray(x) - self.dx) / self.L).astype(np.int64), \
               np.floor((np.asarray(y) - self.dy) / self.L).astype(np.int64)

    def celula_de(self, x, y):
        return cod(*self._ij(x, y))

    def centros_candidatos(self, x0, y0, x1, y1):
        i0, j0 = self._ij(x0, y0)
        i1, j1 = self._ij(x1, y1)
        i, j = np.meshgrid(np.arange(i0 - 1, i1 + 2), np.arange(j0 - 1, j1 + 2), indexing="ij")
        i, j = i.ravel(), j.ravel()
        return cod(i, j), (i + 0.5) * self.L + self.dx, (j + 0.5) * self.L + self.dy

    def vizinhos(self, cel):
        i, j = cel // 1_000_000 - BASE, cel % 1_000_000 - BASE
        return np.column_stack([cod(i + a, j + b) for a, b in self.desloc_viz])

    def area(self, cel):
        return np.full(len(cel), self.area_km2)

    def dist_borda(self, x, y):
        u = (np.asarray(x) - self.dx) / self.L
        v = (np.asarray(y) - self.dy) / self.L
        u, v = u - np.floor(u), v - np.floor(v)
        return self.L * np.minimum.reduce([u, 1 - u, v, 1 - v])


class HexPlano:
    """Hexágonos regulares 'pointy-top' no plano Albers (coordenadas axiais q, r). Não é o H3."""
    forma = "hexagono_plano"
    _DIRS = [(1, 0), (1, -1), (0, -1), (-1, 0), (-1, 1), (0, 1)]

    def __init__(self, area_km2: float, dx: float = 0.0, dy: float = 0.0):
        self.area_km2 = float(area_km2)
        self.s = np.sqrt(2 * area_km2 * 1e6 / (3 * np.sqrt(3)))  # raio circunscrito (m)
        self.a = self.s * np.sqrt(3) / 2  # apótema (m)
        self.dx, self.dy = float(dx), float(dy)

    def _qr(self, x, y):
        px, py = np.asarray(x, float) - self.dx, np.asarray(y, float) - self.dy
        q = (np.sqrt(3) / 3 * px - py / 3) / self.s
        r = (2 / 3 * py) / self.s
        cx, cz = q, r
        cy = -cx - cz
        rx, ry, rz = np.round(cx), np.round(cy), np.round(cz)
        ex, ey, ez = np.abs(rx - cx), np.abs(ry - cy), np.abs(rz - cz)
        fx = (ex > ey) & (ex > ez)
        fz = ~fx & (ez >= ey)
        rx = np.where(fx, -ry - rz, rx)
        rz = np.where(fz, -rx - ry, rz)
        return rx.astype(np.int64), rz.astype(np.int64)

    def _centro(self, q, r):
        return self.s * np.sqrt(3) * (q + r / 2) + self.dx, self.s * 1.5 * r + self.dy

    def celula_de(self, x, y):
        return cod(*self._qr(x, y))

    def centros_candidatos(self, x0, y0, x1, y1):
        r0 = int(np.floor((y0 - self.dy) / (1.5 * self.s))) - 2
        r1 = int(np.ceil((y1 - self.dy) / (1.5 * self.s))) + 2
        qs, rs = [], []
        for r in range(r0, r1 + 1):
            qa = int(np.floor((x0 - self.dx) / (self.s * np.sqrt(3)) - r / 2)) - 2
            qb = int(np.ceil((x1 - self.dx) / (self.s * np.sqrt(3)) - r / 2)) + 2
            q = np.arange(qa, qb + 1)
            qs.append(q); rs.append(np.full(len(q), r))
        q, r = np.concatenate(qs), np.concatenate(rs)
        cx, cy = self._centro(q, r)
        return cod(q, r), cx, cy

    def vizinhos(self, cel):
        q, r = cel // 1_000_000 - BASE, cel % 1_000_000 - BASE
        return np.column_stack([cod(q + a, r + b) for a, b in self._DIRS])

    def area(self, cel):
        return np.full(len(cel), self.area_km2)

    def dist_borda(self, x, y):
        q, r = self._qr(x, y)
        cx, cy = self._centro(q, r)
        px, py = np.asarray(x) - cx, np.asarray(y) - cy
        proj = [np.abs(px * np.cos(t) + py * np.sin(t)) for t in np.deg2rad([0, 60, 120])]
        return self.a - np.maximum.reduce(proj)


class H3Fixo:
    """Adaptador do H3 r7 (geodetect.grades.GradeH3). Estrutura geográfica fixa: sem deslocamento."""
    forma = "hexagono_h3"
    dx = dy = 0.0

    def __init__(self, res: int = 7):
        self.g = GradeH3(res)
        self.res = res

    def celula_de(self, x, y):
        lon, lat = _PARA_LONLAT.transform(np.asarray(x), np.asarray(y))
        return np.array([h3.latlng_to_cell(la, lo, self.res) for la, lo in zip(lat, lon)], dtype=object)

    def universo(self, quad_ids):
        mapa = self.g.celulas_por_quadrado(quad_ids)
        return mapa.index.to_numpy(dtype=object), quad_int(mapa.to_numpy())

    def vizinhos(self, cel):
        v = self.g.vizinhos(cel)
        return np.array([v[c] for c in cel], dtype=object)

    def area(self, cel):
        return self.g.area_km2(cel).to_numpy()

    def dist_borda(self, x, y):
        cel = self.celula_de(x, y)
        bordas = [self.g._poligono_m(c).boundary for c in cel]
        return shapely.distance(shapely.points(np.asarray(x), np.asarray(y)), bordas)


def universo_plano(grade, quad_ids) -> tuple[np.ndarray, np.ndarray]:
    """Células cujo CENTRO cai nos quadrados de 5 km do universo (mesma regra do protocolo)."""
    qi = quad_int(quad_ids)
    i, j = qi // 1_000_000 - BASE, qi % 1_000_000 - BASE
    cel, cx, cy = grade.centros_candidatos(i.min() * CELULA_M, j.min() * CELULA_M,
                                           (i.max() + 1) * CELULA_M, (j.max() + 1) * CELULA_M)
    sq = quad_de(cx, cy)
    ok = np.isin(sq, qi)
    return cel[ok], sq[ok]


# ---------------------------------------------------------------------------------------------------------------
def preparar_dados():
    g = carregar_preparado()
    g = g[g["view_date"] <= DEV[1]].copy()  # NADA do período reservado é lido
    assert g["view_date"].max() <= pd.Timestamp(DEV[1])
    origens = origens_dev()
    quad_max = universo_quadrados(*[disponiveis(g, origens[-1])[c].to_numpy() for c in ("cel_i", "cel_j")])
    return g, origens, quad_max


def pixels(quad_max):
    qi = quad_int(quad_max)
    i, j = qi // 1_000_000 - BASE, qi % 1_000_000 - BASE
    n = CELULA_M // PIXEL_M
    a, b = np.meshgrid(np.arange(n), np.arange(n), indexing="ij")
    px = (i[:, None] * CELULA_M + (a.ravel()[None, :] + 0.5) * PIXEL_M).ravel()
    py = (j[:, None] * CELULA_M + (b.ravel()[None, :] + 0.5) * PIXEL_M).ravel()
    return px, py, np.repeat(qi, n * n)


def avaliar(grade, g, origens, quad_max, pix=None, guardar_pix=False):
    """Recall por origem/modelo/orçamento, captura de cada alerta-alvo e seleção em pixels (2%)."""
    if isinstance(grade, H3Fixo):
        cel_all, sq_all = grade.universo(quad_max)
    else:
        cel_all, sq_all = universo_plano(grade, quad_max)
    viz_all = grade.vizinhos(cel_all)
    area_all = grade.area(cel_all)
    ev = pd.DataFrame({"chave": g["chave"].to_numpy(), "view_date": g["view_date"].to_numpy(),
                       "celula": grade.celula_de(g["cx"].to_numpy(), g["cy"].to_numpy()),
                       "cx": g["cx"].to_numpy(), "cy": g["cy"].to_numpy()})
    pix_cel = grade.celula_de(pix[0], pix[1]) if pix is not None else None
    rec, alertas, sel_pix = [], [], {}
    for t in origens:
        d = disponiveis(g, t)
        u = quad_int(universo_quadrados(d["cel_i"].to_numpy(), d["cel_j"].to_numpy()))
        no_u = np.isin(sq_all, u)
        cel, viz, area = cel_all[no_u], viz_all[no_u], area_all[no_u]
        area_ref = 25.0 * len(u)
        sc = pontuacoes(cel, viz, disponiveis(ev, t), t, MODELOS)
        tgt = alvo(ev, t)
        y = tgt.groupby("celula").size().reindex(cel).fillna(0).to_numpy(float)
        pos = pd.Series(np.arange(len(cel)), index=cel)
        idx = pos.reindex(tgt["celula"].to_numpy()).to_numpy()
        dentro = ~np.isnan(idx)
        ii = np.nan_to_num(idx, nan=0).astype(int)
        al = pd.DataFrame({"origem": t.date().isoformat(), "chave": tgt["chave"].to_numpy(),
                           "dist_borda_m": grade.dist_borda(tgt["cx"].to_numpy(), tgt["cy"].to_numpy()),
                           "hist_propria": np.where(dentro, sc["A"][ii] > 0, False),
                           "hist_vizinhos": np.where(dentro, (sc["C"][ii] - sc["A"][ii]) > 0, False)})
        for m, s in sc.items():
            for f in ORCAMENTOS:
                k = k_orcamento(f, area_ref, float(area.mean()))
                p = prob_selecao(s, k)
                rec.append({"origem": t.date().isoformat(), "modelo": m, "orcamento": f, "k": k,
                            "alertas_alvo": len(tgt), "capturados": float((p * y).sum()),
                            "recall_alertas": float((p * y).sum()) / len(tgt),
                            "area_selecionada_km2": float((p * area).sum()), "area_orcamento_km2": f * area_ref})
                if f == PRIMARIO:
                    al[f"p_{m}"] = np.where(dentro, p[ii], 0.0)
                    if pix is not None:
                        pin = np.isin(pix[2], u)
                        sel = cel[selecao_deterministica(s, k)]
                        mask = pin & np.isin(pix_cel, sel)
                        ps = pd.Series(s, index=cel).reindex(pix_cel).fillna(0).to_numpy(np.float32)
                        ps[~pin] = np.nan
                        sel_pix[(t.date().isoformat(), m)] = (mask, ps)
        alertas.append(al)
    estrut = estrutura(cel, viz, area)
    return pd.DataFrame(rec), pd.concat(alertas, ignore_index=True), sel_pix, estrut


def estrutura(cel, viz, area):
    """Estrutura no universo da última origem de desenvolvimento."""
    s = set(cel.tolist())
    dentro = np.vectorize(lambda c: c in s, otypes=[bool])(viz)
    return {"celulas_elegiveis": len(cel), "vizinhos_por_celula": viz.shape[1],
            "relacoes_direcionadas_no_universo": int(dentro.sum()),
            "arestas_nao_direcionadas_no_universo": int(dentro.sum() // 2),
            "area_media_celula_km2": float(area.mean()),
            "area_vizinhanca_km2": float(area.mean() * viz.shape[1]),
            "area_celula_mais_vizinhanca_km2": float(area.mean() * (viz.shape[1] + 1))}


def spearman(a, b) -> float:
    """Correlação de postos entre pontuações por pixel, sobre TODOS os pixels do universo (zeros incluídos).
    Condicionar a pixels com pontuação > 0 cria correlação negativa artificial (zeros de uma grade × positivos da outra)."""
    ok = ~np.isnan(a) & ~np.isnan(b)
    if ok.sum() < 3:
        return np.nan
    return float(np.corrcoef(pd.Series(a[ok]).rank(), pd.Series(b[ok]).rank())[0, 1])


def iou(a, b) -> float:
    u = (a | b).sum()
    return float((a & b).sum() / u) if u else np.nan


# ---------------------------------------------------------------------------------------------------------------
def familias(area_h3: float, rng: np.random.Generator):
    sis = [(a / 4, b / 4) for a in range(4) for b in range(4)]  # deslocamentos sistemáticos (fração do lado)
    lado_m = np.sqrt(area_h3 * 1e6)
    fam = {
        "quadrado_2.5km": [Quadrada(2500, u * 2500, v * 2500) for u, v in sis],
        "quadrado_2.5km_vn": [Quadrada(2500, u * 2500, v * 2500, viz="vn") for u, v in sis],
        "quadrado_aream_h3": [Quadrada(lado_m, u * lado_m, v * lado_m) for u, v in sis],
    }
    for nome, ar in (("hex_plano_6.25km2", 6.25), ("hex_plano_aream_h3", area_h3)):
        h0 = HexPlano(ar)
        off = [(0.0, 0.0)] + [(rng.uniform(0, h0.s * np.sqrt(3)), rng.uniform(0, 3 * h0.s)) for _ in range(N_DESLOC - 1)]
        fam[nome] = [HexPlano(ar, dx, dy) for dx, dy in off]
    return fam


def analise():
    SAIDA.mkdir(parents=True, exist_ok=True)
    t0 = time.perf_counter()
    g, origens, quad_max = preparar_dados()
    pix = pixels(quad_max)
    print(f"dados até {g['view_date'].max().date()} | {len(origens)} origens | {len(pix[0]):,} pixels de {PIXEL_M} m")

    # sanidade das grades planas (Voronoi: o ponto pertence ao centro mais próximo; borda ≥ 0)
    rng_s = np.random.default_rng(1)
    xs, ys = rng_s.uniform(0, 50_000, 20_000) + 300_000, rng_s.uniform(0, 50_000, 20_000) + 2_800_000
    for hx in (HexPlano(6.25, 123.0, 456.0), Quadrada(2500, 700.0, 300.0)):
        d = hx.dist_borda(xs, ys)
        assert (d >= -1e-6).all() and d.max() <= (hx.a if isinstance(hx, HexPlano) else hx.L / 2) + 1e-6
    hx = HexPlano(6.25, 123.0, 456.0)
    q, r = hx._qr(xs, ys)
    cxy = np.column_stack(hx._centro(q, r))
    for a, b in HexPlano._DIRS:
        nxy = np.column_stack(hx._centro(q + a, r + b))
        assert (np.hypot(*(np.column_stack([xs, ys]) - cxy).T) <= np.hypot(*(np.column_stack([xs, ys]) - nxy).T) + 1e-6).all()

    # H3 r7 (realização única) e validação contra a avaliação final em modo dev
    h3g = H3Fixo(7)
    configs = [("h3_r7", 0, h3g)]
    rec_h3, al_h3, pix_h3, est_h3 = avaliar(h3g, g, origens, quad_max, pix)
    area_h3 = est_h3["area_media_celula_km2"]
    fam = familias(area_h3, np.random.default_rng(SEMENTE))
    for nome, lst in fam.items():
        configs += [(nome, i, gr) for i, gr in enumerate(lst)]

    recs, als, sobre, estr = [rec_h3.assign(familia="h3_r7", desloc=0, dx=0.0, dy=0.0)], \
        [al_h3.assign(familia="h3_r7", desloc=0, area_celula_km2=area_h3)], [], [{"familia": "h3_r7", **est_h3}]
    refs = {"h3_r7": pix_h3}
    for nome, i, gr in configs[1:]:
        r_, a_, p_, e_ = avaliar(gr, g, origens, quad_max, pix)
        recs.append(r_.assign(familia=nome, desloc=i, dx=gr.dx, dy=gr.dy))
        als.append(a_.assign(familia=nome, desloc=i, area_celula_km2=gr.area_km2))
        if i == 0:
            refs[nome] = p_
            estr.append({"familia": nome, **e_})
        comparar = {"mesma_familia_desloc0": refs[nome], "h3_r7": refs["h3_r7"]}
        if "quadrado_2.5km" in refs and nome != "quadrado_2.5km":
            comparar["quadrado_2.5km_desloc0"] = refs["quadrado_2.5km"]
        for ref_nome, ref in comparar.items():
            for (o, m), (mask, ps) in p_.items():
                rm, rs = ref[(o, m)]
                sobre.append({"familia": nome, "desloc": i, "referencia": ref_nome, "origem": o, "modelo": m,
                              "iou_area_selecionada": iou(mask, rm), "spearman_pontuacao_pixel": spearman(ps, rs),
                              "area_selecionada_km2": mask.sum() * (PIXEL_M / 1000) ** 2})
        print(f"  {nome:22s} desloc {i:2d}  ({time.perf_counter() - t0:5.0f} s)")
    # H3 contra o quadrado de 2,5 km sem deslocamento (sobreposição entre formas)
    for (o, m), (mask, ps) in pix_h3.items():
        rm, rs = refs["quadrado_2.5km"][(o, m)]
        sobre.append({"familia": "h3_r7", "desloc": 0, "referencia": "quadrado_2.5km_desloc0", "origem": o, "modelo": m,
                      "iou_area_selecionada": iou(mask, rm), "spearman_pontuacao_pixel": spearman(ps, rs),
                      "area_selecionada_km2": mask.sum() * (PIXEL_M / 1000) ** 2})

    rec = pd.concat(recs, ignore_index=True)
    al = pd.concat(als, ignore_index=True)
    sob = pd.DataFrame(sobre)
    rec.to_csv(SAIDA / "recall_por_configuracao.csv", index=False, float_format="%.5f")
    sob.to_csv(SAIDA / "sobreposicao_e_pontuacao.csv", index=False, float_format="%.4f")
    pd.DataFrame(estr).to_csv(SAIDA / "estrutura_vizinhanca.csv", index=False, float_format="%.3f")

    # validação: deslocamento zero reproduz a avaliação final em modo dev
    ref = pd.read_csv(RAIZ / "results" / "avaliacao_final" / "dev" / "por_origem.csv")
    val = []
    for fam_nome, grade_ref in (("h3_r7", "h3_r7"), ("quadrado_2.5km", "quadrado_2.5km")):
        mine = rec[(rec.familia == fam_nome) & (rec.desloc == 0)]
        for _, r in mine.iterrows():
            o = ref[(ref.grade == grade_ref) & (ref.modelo == f"{grade_ref}_{r.modelo}") &
                    (ref.origem == r.origem) & np.isclose(ref.orcamento, r.orcamento)].iloc[0]
            val.append({"grade": grade_ref, "modelo": r.modelo, "origem": r.origem, "orcamento": r.orcamento,
                        "k_aqui": r.k, "k_ref": o.k, "recall_aqui": r.recall_alertas, "recall_ref": o.recall_alertas,
                        "dif_abs": abs(r.recall_alertas - o.recall_alertas)})
    val = pd.DataFrame(val)
    val.to_csv(SAIDA / "validacao_vs_avaliacao_final_dev.csv", index=False, float_format="%.6f")
    assert (val.k_aqui == val.k_ref).all() and val.dif_abs.max() < 1e-4, val.sort_values("dif_abs").tail()
    print(f"validação: {len(val)} linhas, k idêntico, dif. máx. de recall {val.dif_abs.max():.1e}")

    # recall agregado (alertas capturados ÷ alertas-alvo, somando as 6 origens) por configuração
    agg = (rec.groupby(["familia", "desloc", "modelo", "orcamento"])[["capturados", "alertas_alvo",
                                                                         "area_selecionada_km2", "area_orcamento_km2"]]
           .sum().reset_index())
    agg["recall_agregado"] = agg.capturados / agg.alertas_alvo
    agg["razao_area"] = agg.area_selecionada_km2 / agg.area_orcamento_km2
    agg.to_csv(SAIDA / "recall_agregado_por_configuracao.csv", index=False, float_format="%.5f")
    res = (agg.groupby(["familia", "modelo", "orcamento"]).recall_agregado
           .agg(n="size", media="mean", dp="std", minimo="min", maximo="max",
                p05=lambda x: x.quantile(0.05), p95=lambda x: x.quantile(0.95)).reset_index())
    res["amplitude"] = res.maximo - res.minimo
    h3v = agg[agg.familia == "h3_r7"].set_index(["modelo", "orcamento"]).recall_agregado
    res["h3_r7"] = [h3v[(m, f)] for m, f in zip(res.modelo, res.orcamento)]
    res["pct_desloc_abaixo_h3"] = [(agg[(agg.familia == fa) & (agg.modelo == m) & (agg.orcamento == f)]
                                    .recall_agregado < h3v[(m, f)]).mean()
                                   for fa, m, f in zip(res.familia, res.modelo, res.orcamento)]
    res.to_csv(SAIDA / "resumo_deslocamentos.csv", index=False, float_format="%.4f")

    # bordas: distância do centroide do alerta-alvo à borda, normalizada por √área
    al["dist_norm"] = al.dist_borda_m / np.sqrt(al.area_celula_km2 * 1e6)
    al["faixa"] = pd.cut(al.dist_norm, [0, 0.05, 0.10, 0.20, 0.30, 0.60], include_lowest=True)
    al.to_csv(SAIDA / "alertas_alvo_por_configuracao.csv.gz", index=False, float_format="%.4f")
    borda = (al.groupby(["familia", "faixa"], observed=True)
             .agg(n=("chave", "size"), p_captura_A=("p_A", "mean"), p_captura_C=("p_C", "mean"),
                  com_historico_proprio=("hist_propria", "mean"), com_historico_vizinho=("hist_vizinhos", "mean"))
             .reset_index())
    borda["fracao_alertas"] = borda.n / borda.groupby("familia").n.transform("sum")
    borda.to_csv(SAIDA / "borda.csv", index=False, float_format="%.4f")
    # mudança do status de captura de cada alerta entre deslocamentos (sensibilidade aos limites)
    flip = (al[al.familia != "h3_r7"].groupby(["familia", "origem", "chave"])
            .agg(pA_min=("p_A", "min"), pA_max=("p_A", "max"), pC_min=("p_C", "min"), pC_max=("p_C", "max"),
                 hist_var=("hist_propria", lambda x: x.nunique() > 1)).reset_index())
    flip_res = (flip.groupby("familia")
                .agg(alertas=("chave", "size"),
                     muda_captura_A=("pA_max", lambda s: ((s - flip.loc[s.index, "pA_min"]) > 0.5).mean()),
                     muda_captura_C=("pC_max", lambda s: ((s - flip.loc[s.index, "pC_min"]) > 0.5).mean()),
                     muda_historico_proprio=("hist_var", "mean")).reset_index())
    flip_res.to_csv(SAIDA / "sensibilidade_limites.csv", index=False, float_format="%.4f")

    sob = sob[~((sob.referencia == "mesma_familia_desloc0") & (sob.desloc == 0))]  # exclui a comparação consigo mesma
    sob_res = (sob.groupby(["familia", "referencia", "modelo"])
               .agg(iou_medio=("iou_area_selecionada", "mean"), iou_min=("iou_area_selecionada", "min"),
                    spearman_medio=("spearman_pontuacao_pixel", "mean")).reset_index())
    sob_res.to_csv(SAIDA / "sobreposicao_resumo.csv", index=False, float_format="%.4f")

    (SAIDA / "execucao.json").write_text(json.dumps({
        "natureza": "EXPLORATÓRIA, somente desenvolvimento; não altera nem substitui a avaliação final",
        "dados_ate": str(g["view_date"].max().date()), "origens": [t.date().isoformat() for t in origens],
        "w": W, "orcamentos": ORCAMENTOS, "deslocamentos_por_familia": N_DESLOC, "semente": SEMENTE,
        "pixel_m": PIXEL_M, "area_media_h3_r7_km2": area_h3, "tempo_s": round(time.perf_counter() - t0, 1),
        "versoes": {p: __import__(p).__version__ for p in ("numpy", "pandas", "geopandas", "shapely", "h3")},
        "python": platform.python_version(), "plataforma": platform.platform()}, indent=2, ensure_ascii=False),
        encoding="utf-8")
    figuras(agg, borda)
    pd.set_option("display.width", 220)
    print(res[res.orcamento == PRIMARIO].round(4).to_string(index=False))
    print(flip_res.round(3).to_string(index=False))
    print(sob_res.round(3).to_string(index=False))


def figuras(agg, borda):
    plt.rcParams.update({"font.size": 9, "axes.spines.top": False, "axes.spines.right": False})
    ordem = ["quadrado_2.5km", "quadrado_aream_h3", "quadrado_2.5km_vn", "hex_plano_6.25km2", "hex_plano_aream_h3"]
    fig, axs = plt.subplots(1, 2, figsize=(11, 4), sharey=True)
    for ax, m in zip(axs, ["A", "C"]):
        d = agg[(agg.modelo == m) & (agg.orcamento == PRIMARIO)]
        for x, fa in enumerate(ordem):
            v = d[d.familia == fa].recall_agregado
            ax.scatter(np.full(len(v), x) + np.random.default_rng(x).uniform(-0.15, 0.15, len(v)), v, s=14,
                       color="#2a6f97" if fa.startswith("quad") else "#e07a1f", alpha=0.8)
            ax.hlines(v.mean(), x - 0.3, x + 0.3, color="#333")
        ax.axhline(d[d.familia == "h3_r7"].recall_agregado.iloc[0], color="#8c3b00", ls="--", lw=1, label="H3 r7 (única realização)")
        ax.set_xticks(range(len(ordem))); ax.set_xticklabels([o.replace("_", "\n", 1) for o in ordem], fontsize=7)
        ax.set_title(f"Modelo {m}: Recall@{PRIMARIO:.0%} agregado (dev, {N_DESLOC} deslocamentos)", fontsize=9)
        ax.legend(frameon=False, fontsize=7)
    axs[0].set_ylabel("recall de alertas futuros")
    fig.tight_layout(); fig.savefig(SAIDA / "fig_deslocamentos.png", dpi=160); plt.close(fig)

    fig, axs = plt.subplots(1, 2, figsize=(11, 3.8), sharey=True)
    for ax, col in zip(axs, ["p_captura_A", "com_historico_proprio"]):
        for fa, cor in [("h3_r7", "#8c3b00"), ("quadrado_2.5km", "#2a6f97"), ("hex_plano_6.25km2", "#e07a1f")]:
            d = borda[borda.familia == fa]
            ax.plot(range(len(d)), d[col], "o-", color=cor, label=fa)
        ax.set_xticks(range(len(d))); ax.set_xticklabels([str(f) for f in d.faixa], fontsize=7)
        ax.set_xlabel("distância do centroide à borda da célula ÷ √área")
        ax.set_title({"p_captura_A": "P(captura) com modelo A, 2%", "com_historico_proprio": "célula com histórico próprio (24 m)"}[col])
        ax.legend(frameon=False, fontsize=7)
    fig.tight_layout(); fig.savefig(SAIDA / "fig_borda.png", dpi=160); plt.close(fig)


# ---------------------------------------------------------------------------------------------------------------
def bench_uma(grade_nome: str) -> dict:
    """Uma execução do pipeline do protocolo (classes de geodetect/) para uma grade, medida por etapa."""
    g, origens, quad_max = preparar_dados()
    gr = GradeH3(7) if grade_nome == "h3_r7" else GradeQuadrada(2500)
    tracemalloc.start()
    tempos = {}
    t = time.perf_counter()
    cent = gr.celula_dos_centroides(g)
    tempos["atribuicao_centroides_s"] = time.perf_counter() - t
    t = time.perf_counter()
    mapa = gr.celulas_por_quadrado(quad_max)
    cel_all = mapa.index.to_numpy()
    viz = gr.vizinhos(cel_all)
    viz = np.array([viz[c] for c in cel_all], dtype=object)
    area = gr.area_km2(cel_all).to_numpy()
    tempos["universo_e_vizinhanca_s"] = time.perf_counter() - t
    ev = g.assign(celula=cent.to_numpy())[["chave", "view_date", "celula"]]
    t = time.perf_counter()
    for o in origens:
        d = disponiveis(g, o)
        u = set(universo_quadrados(d["cel_i"].to_numpy(), d["cel_j"].to_numpy()))
        no_u = mapa.isin(u).to_numpy()
        sc = pontuacoes(cel_all[no_u], viz[no_u], disponiveis(ev, o), o, MODELOS)
        for s in sc.values():
            for f in ORCAMENTOS:
                prob_selecao(s, k_orcamento(f, 25.0 * len(u), float(area[no_u].mean())))
    tempos["pontuacao_e_selecao_6_origens_s"] = time.perf_counter() - t
    _, pico_pipeline = tracemalloc.get_traced_memory()
    t = time.perf_counter()
    gr.intersecoes(g[g["view_date"] >= origens[0]])  # métrica secundária (recall por área)
    tempos["intersecoes_poligonos_dev_s"] = time.perf_counter() - t
    _, pico = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    tempos["total_sem_intersecoes_s"] = sum(v for k, v in tempos.items() if k != "intersecoes_poligonos_dev_s")
    return {"grade": grade_nome, **{k: round(v, 4) for k, v in tempos.items()},
            "pico_tracemalloc_pipeline_mb": round(pico_pipeline / 2**20, 1),
            "pico_tracemalloc_com_intersecoes_mb": round(pico / 2**20, 1),
            "rss_max_processo_mb": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 2**20, 1),
            "celulas_universo": len(cel_all)}


def bench():
    SAIDA.mkdir(parents=True, exist_ok=True)
    linhas = []
    for rep in range(5):
        for nome in ("quadrado_2.5km", "h3_r7") if rep % 2 == 0 else ("h3_r7", "quadrado_2.5km"):
            out = subprocess.run([sys.executable, __file__, "--bench-uma", nome], capture_output=True, text=True,
                                 check=True, cwd=RAIZ).stdout.strip().splitlines()[-1]
            linhas.append({"repeticao": rep, **json.loads(out)})
            print(linhas[-1])
    b = pd.DataFrame(linhas)
    b.to_csv(SAIDA / "custo_benchmark_execucoes.csv", index=False)
    b.drop(columns="repeticao").groupby("grade").median().to_csv(SAIDA / "custo_benchmark_mediana.csv", float_format="%.3f")
    try:
        cpu = subprocess.run(["sysctl", "-n", "machdep.cpu.brand_string"], capture_output=True, text=True).stdout.strip()
        mem = int(subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True, text=True).stdout) / 2**30
    except Exception:  # noqa: BLE001
        cpu, mem = platform.processor(), float("nan")
    (SAIDA / "custo_ambiente.json").write_text(json.dumps({
        "metodologia": "5 repetições por grade, ordem alternada, cada uma em subprocesso novo; carga dos dados "
                       "não cronometrada (comum às grades); mediana reportada; tracemalloc mede alocações Python "
                       "das etapas; ru_maxrss é o pico do processo inteiro (inclui dados e bibliotecas)",
        "dados": "somente desenvolvimento (view_date ≤ 2025-06-30), 6 origens",
        "cpu": cpu, "memoria_gb": round(mem, 1), "python": platform.python_version(), "plataforma": platform.platform(),
        "versoes": {p: __import__(p).__version__ for p in ("numpy", "pandas", "geopandas", "shapely", "h3")}},
        indent=2, ensure_ascii=False), encoding="utf-8")
    print(b.drop(columns="repeticao").groupby("grade").median().T)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--bench", action="store_true")
    ap.add_argument("--bench-uma", choices=["h3_r7", "quadrado_2.5km"])
    a = ap.parse_args()
    if a.bench_uma:
        print(json.dumps(bench_uma(a.bench_uma)))
    elif a.bench:
        bench()
    else:
        analise()
