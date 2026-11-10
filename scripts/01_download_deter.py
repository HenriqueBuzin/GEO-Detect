"""Baixa os alertas DETER Amazônia (INPE/TerraBrasilis) via WFS.

Por padrão baixa TODOS os alertas da classe MINERACAO no Pará (todo o histórico),
para que a auditoria possa contextualizar o recorte 2024–2025.

Também baixa o limite estadual do Pará (IBGE) para os mapas.

Cada execução grava um arquivo de metadados (URL, filtro, data de atualização
do DETER, contagem e SHA-256) para garantir rastreabilidade.

Uso:
    python scripts/01_download_deter.py
    python scripts/01_download_deter.py --uf PA --classe MINERACAO --saida data/raw
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

WFS = "https://terrabrasilis.dpi.inpe.br/geoserver/deter-amz/ows"
LAYER = "deter-amz:deter_amz"
UPDATED_LAYER = "deter-amz:updated_date"
IBGE_UF = (
    "https://servicodados.ibge.gov.br/api/v3/malhas/estados/{cod}"
    "?formato=application/vnd.geo%2Bjson&qualidade=intermediaria"
)
UF_IBGE = {"PA": 15, "AM": 13, "MT": 51, "RO": 11, "RR": 14, "AP": 16, "AC": 12, "TO": 17, "MA": 21}
PAGE = 1000
HEADERS = {"User-Agent": "GEO-Detect research script (python-requests)"}


def wfs_get(params: dict, timeout: int = 180) -> requests.Response:
    base = {"service": "WFS", "version": "2.0.0", "request": "GetFeature", "typeNames": LAYER}
    for tentativa in range(4):
        try:
            r = requests.get(WFS, params={**base, **params}, headers=HEADERS, timeout=timeout)
            r.raise_for_status()
            return r
        except requests.RequestException as exc:
            if tentativa == 3:
                raise
            espera = 5 * (tentativa + 1)
            print(f"  falha ({exc}); nova tentativa em {espera}s")
            time.sleep(espera)
    raise RuntimeError("inalcançável")


def baixar_alertas(cql: str) -> dict:
    hits = wfs_get({"resultType": "hits", "CQL_FILTER": cql}).text
    total = int(hits.split('numberMatched="')[1].split('"')[0])
    print(f"Registros no servidor para o filtro: {total}")

    features: list[dict] = []
    start = 0
    while start < total:
        r = wfs_get(
            {
                "CQL_FILTER": cql,
                "outputFormat": "application/json",
                "count": PAGE,
                "startIndex": start,
                "sortBy": "gid",  # ordenação estável para paginação
                "srsName": "EPSG:4674",  # SIRGAS 2000 geográfico (CRS nativo do DETER)
            }
        )
        lote = r.json()["features"]
        if not lote:
            break
        features.extend(lote)
        start += len(lote)
        print(f"  {start}/{total}")

    if len(features) != total:
        raise RuntimeError(f"Esperados {total} registros, recebidos {len(features)}")
    return {
        "type": "FeatureCollection",
        "crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:EPSG::4674"}},
        "features": features,
    }


def data_atualizacao_deter() -> str | None:
    r = requests.get(
        WFS,
        params={
            "service": "WFS", "version": "2.0.0", "request": "GetFeature",
            "typeNames": UPDATED_LAYER, "outputFormat": "application/json",
        },
        headers=HEADERS, timeout=60,
    )
    r.raise_for_status()
    feats = r.json().get("features", [])
    return feats[0]["properties"].get("updated_date") if feats else None


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for bloco in iter(lambda: f.read(1 << 20), b""):
            h.update(bloco)
    return h.hexdigest()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--uf", default="PA")
    ap.add_argument("--classe", default="MINERACAO")
    ap.add_argument("--saida", default="data/raw", type=Path)
    args = ap.parse_args()
    args.saida.mkdir(parents=True, exist_ok=True)

    cql = f"classname='{args.classe}' AND uf='{args.uf}'"
    print(f"Filtro CQL: {cql}")
    fc = baixar_alertas(cql)
    nome = f"deter_amz_{args.classe.lower()}_{args.uf.lower()}.geojson"
    destino = args.saida / nome
    destino.write_text(json.dumps(fc), encoding="utf-8")

    limite = args.saida / f"limite_{args.uf.lower()}_ibge.geojson"
    r = requests.get(IBGE_UF.format(cod=UF_IBGE[args.uf]), headers=HEADERS, timeout=60)
    r.raise_for_status()
    limite.write_bytes(r.content)

    meta = {
        "fonte": "INPE/TerraBrasilis — DETER Amazônia (WFS)",
        "endpoint": WFS,
        "camada": LAYER,
        "filtro_cql": cql,
        "crs": "EPSG:4674",
        "registros": len(fc["features"]),
        "deter_updated_date": data_atualizacao_deter(),
        "baixado_em_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "arquivo": str(destino),
        "sha256": sha256(destino),
        "limite_uf": {"fonte": "IBGE malhas v3", "arquivo": str(limite), "sha256": sha256(limite)},
        "observacao": (
            "O WFS público expõe apenas os avisos DETER em área de floresta. "
            "Os avisos de não floresta (experimentais) não estão nesta camada."
        ),
    }
    (args.saida / "download_metadata.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(meta, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
