"""Obtém insumos oficiais, verifica a cópia congelada e reproduz os resultados do artigo."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.request import Request, urlopen

RAIZ = Path(__file__).resolve().parents[1]


def sha256(arquivo: Path) -> str:
    with arquivo.open('rb') as entrada:
        return hashlib.file_digest(entrada, 'sha256').hexdigest()


def verificar(arquivo: Path, digest: str) -> None:
    if not arquivo.is_file() or sha256(arquivo) != digest:
        raise ValueError(f'Arquivo ausente ou SHA-256 divergente: {arquivo.relative_to(RAIZ)}')


def obter(arquivo: Path, digest: str, url: str) -> None:
    if arquivo.exists():
        verificar(arquivo, digest)
        return
    arquivo.parent.mkdir(parents=True, exist_ok=True)
    requisicao = Request(url, headers={'User-Agent': 'GEO-Detect reproducibility'})
    with tempfile.TemporaryDirectory(dir=arquivo.parent) as temporario:
        destino = Path(temporario) / arquivo.name
        with urlopen(requisicao, timeout=60) as resposta, destino.open('wb') as saida:
            shutil.copyfileobj(resposta, saida)
        verificar(destino, digest)
        destino.replace(arquivo)


def preparar_fontes() -> None:
    deter = json.loads((RAIZ / 'data/raw/download_metadata.json').read_text())
    verificar(RAIZ / deter['arquivo'], deter['sha256'])
    fontes = json.loads((RAIZ / 'reproducao/fontes_auxiliares.json').read_text())
    for nome, digest in fontes['arquivos_sha256'].items():
        arquivo = Path(nome)
        url = (fontes['hydro_url'] if arquivo.suffix == '.zip'
               else fontes['ibge_url'] + arquivo.name)
        obter(RAIZ / arquivo, digest, url)
    print('Cópia congelada do DETER e cinco arquivos auxiliares verificados.', flush=True)


def executar(*argumentos: str) -> None:
    subprocess.run([sys.executable, *argumentos], cwd=RAIZ, check=True)


def conferir_resultados() -> None:
    with (RAIZ / 'reproducao/resultados_esperados.csv').open() as arquivo:
        esperados = list(csv.DictReader(arquivo))
    linhas = {}
    for relativo in {linha['arquivo'] for linha in esperados}:
        with (RAIZ / relativo).open() as arquivo:
            linhas[relativo] = {(r['modelo'], r['origem']): r for r in csv.DictReader(arquivo)}
    for esperado in esperados:
        nome = esperado['modelo']
        origem = esperado['origem']
        obtido = linhas[esperado['arquivo']][nome, origem]
        for campo in ('alertas', 'celulas_avaliadas', 'celulas_positivas', 'celulas_positivas_avaliadas'):
            if int(obtido[campo]) != int(esperado[campo]):
                raise ValueError(f'{nome}, {origem}: contagem divergente em {campo}')
        if not math.isclose(float(obtido['precisao_media']), float(esperado['precisao_media']),
                            rel_tol=0, abs_tol=1e-7):
            raise ValueError(f'{nome}, {origem}: AP divergente da referência')
    print(f'{len(esperados)} resultados modelo-trimestre conferidos com os dados de referência.',
          flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    grupo = parser.add_mutually_exclusive_group()
    grupo.add_argument('--verificar-fontes', action='store_true', help='obter e verificar os arquivos de entrada')
    grupo.add_argument('--conferir-resultados', action='store_true', help='verificar resultados já calculados')
    args = parser.parse_args()
    if args.conferir_resultados:
        conferir_resultados()
        return
    preparar_fontes()
    if args.verificar_fontes:
        return
    executar('scripts/23_bases_preditores.py')
    executar('scripts/24_lstm_alertas.py')
    executar('scripts/25_mayfield_alertas.py')
    conferir_resultados()
    executar('-c', 'import runpy; runpy.run_path("scripts/12_poster_figures.py")["fig_precisao_alertas"]()')


if __name__ == '__main__':
    main()
