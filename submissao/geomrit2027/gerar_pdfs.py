"""Gera o resumo e a prova de pôster com ReportLab e fontes Arial.

Execute na raiz com o Python do runtime de documentos do Codex, que inclui
ReportLab e Pillow. As figuras são produzidas por scripts/12_poster_figures.py.
"""
from __future__ import annotations

import csv
import re
from pathlib import Path
from xml.sax.saxutils import escape

from PIL import Image as Raster
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A1, A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from reportlab.platypus import Image, KeepTogether, Paragraph, PageBreak, SimpleDocTemplate

FONTE = Path('/System/Library/Fonts/Supplemental')
ORIGEM = Path(__file__).resolve().parent
RAIZ = ORIGEM.parents[1]
SAIDA = RAIZ / 'output/pdf'
FIGURAS = RAIZ / 'results/poster'
TINTA = colors.HexColor('#17262E')
VERDE = colors.HexColor('#13545B')


def texto_marcado(texto: str) -> str:
    texto = escape(texto.strip()).replace('  \n', '<br/>').replace('\n', ' ')
    texto = re.sub(r'\[([^\]]+)\]\((https?://[^)]+)\)', r'<link href="\2" color="#13545B"><u>\1</u></link>', texto)
    texto = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', texto)
    texto = re.sub(r'(?<!\*)\*([^*]+)\*(?!\*)', r'<i>\1</i>', texto)
    texto = re.sub(r'([PR])([₀ₖ]+(?:₋₁)?)',
                   lambda simbolo: f'{simbolo[1]}<sub>{simbolo[2].translate(str.maketrans("₀ₖ₋₁", "0k−1"))}</sub>',
                   texto)
    return re.sub(r'`([^`]+)`', r'<font name="Courier">\g<1></font>', texto)


def formula_marcada(bloco: str) -> str:
    texto = escape(bloco.removeprefix('$$').removesuffix('$$').strip())
    texto = re.sub(r'\\frac\{([^{}]+)\}\{([^{}]+)\}', r'\1 / (\2)', texto)
    texto = re.sub(r'\\mathrm\{([^{}]+)\}', r'\1', texto)
    texto = texto.replace(r'\qquad', '&#160;&#160;&#160;').replace(r'\sum', '∑')
    texto = re.sub(r'_(?:\{([^{}]+)\}|([a-zA-Z0-9]))',
                   lambda indice: f'<sub>{indice[1] or indice[2]}</sub>', texto)
    if '\\' in texto:
        raise ValueError(f'Comando LaTeX não suportado no PDF: {bloco}')
    return texto


def proporcao(caminho: Path) -> float:
    with Raster.open(caminho) as figura:
        return figura.height / figura.width


def rodape(pdf, documento) -> None:
    pdf.setStrokeColor(colors.HexColor('#CDD9D8'))
    pdf.line(20 * mm, 17 * mm, A4[0] - 20 * mm, 17 * mm)
    pdf.setFillColor(VERDE)
    pdf.setFont('Arial', 9)
    pdf.drawString(20 * mm, 12 * mm, 'GEO-Detect / GEOMRIT 2027')
    pdf.drawRightString(A4[0] - 20 * mm, 12 * mm, str(documento.page))


def gerar_a4(nome: str) -> None:
    fonte = (ORIGEM / f'{nome}.md').read_text()
    entrelinhas = 15 if nome == 'artigo' else 16
    corpo = ParagraphStyle('corpo', fontName='Arial', fontSize=12, leading=entrelinhas, spaceAfter=7)
    titulo = ParagraphStyle('titulo', parent=corpo, fontName='Arial-Bold', fontSize=18, leading=22, spaceAfter=12, keepWithNext=True)
    secao = ParagraphStyle('secao', parent=corpo, fontName='Arial-Bold', spaceBefore=9, spaceAfter=5, keepWithNext=True)
    subsecao = ParagraphStyle('subsecao', parent=secao, spaceBefore=5)
    formula = ParagraphStyle('formula', parent=corpo, fontSize=13, alignment=TA_CENTER, spaceBefore=3, keepWithNext=True)
    legenda = ParagraphStyle('legenda', parent=corpo, fontSize=10, leading=12, spaceBefore=5, spaceAfter=8)
    referencia = ParagraphStyle('referencia', parent=corpo, fontSize=10, leading=12)
    conteudo = []
    referencias = False
    for bloco in fonte.strip().split('\n\n'):
        if bloco.startswith('# '):
            conteudo.append(Paragraph(texto_marcado(bloco[2:]), titulo))
        elif bloco.startswith('## '):
            quebra_resumo = nome == 'resumo_expandido' and bloco.startswith(('## 3.', '## 4.'))
            if quebra_resumo:
                conteudo.append(PageBreak())
            referencias = bloco[3:] == 'Referências'
            conteudo.append(Paragraph(texto_marcado(bloco[3:]), secao))
        elif bloco.startswith('### '):
            conteudo.append(Paragraph(texto_marcado(bloco[4:]), subsecao))
        elif bloco.startswith('$$') and bloco.endswith('$$'):
            conteudo.append(Paragraph(formula_marcada(bloco), formula))
        elif bloco.startswith('!['):
            correspondencia = re.fullmatch(r'!\[(.*)\]\(([^)]+)\)', bloco)
            rotulo, arquivo = correspondencia.groups()
            caminho = ORIGEM / arquivo
            largura = 110 * mm
            conteudo.append(KeepTogether([
                Image(str(caminho), width=largura, height=largura * proporcao(caminho)),
                Paragraph(texto_marcado(rotulo), legenda),
            ]))
        else:
            conteudo.append(Paragraph(texto_marcado(bloco), referencia if referencias else corpo))
    documento = SimpleDocTemplate(
        str(SAIDA / f'{nome}.pdf'), pagesize=A4,
        title=fonte.splitlines()[0].removeprefix('# '),
        author='Henrique Buzin',
        leftMargin=20 * mm, rightMargin=20 * mm, topMargin=17 * mm, bottomMargin=21 * mm,
    )
    documento.build(conteudo, onFirstPage=rodape, onLaterPages=rodape)


def gerar_poster() -> None:
    precisao = {}
    for fonte in ('multiescala/bases_agregado.csv', 'redes_temporais/agregado.csv'):
        with (RAIZ / 'results' / fonte).open() as arquivo:
            for linha in csv.DictReader(arquivo):
                precisao[linha['modelo']] = f"{100 * float(linha['precisao_media']):.2f}".replace('.', ',')
    ap_geo = precisao['lstm_kanoga']
    ap_rf = precisao['random_forest_adaptada']
    ap_ann = precisao['ann_mayfield']
    pdf = canvas.Canvas(str(SAIDA / 'poster_preliminar.pdf'), pagesize=A1)
    titulo = (ORIGEM / 'resumo_expandido.md').read_text().splitlines()[0].removeprefix('# ')
    marca, descricao = titulo.split(': ', 1)
    pdf.setTitle(titulo)
    pdf.setAuthor('Henrique Buzin')
    altura = A1[1]

    def caixa(x, topo, largura, tamanho, cor):
        pdf.setFillColor(cor)
        pdf.roundRect(x * mm, altura - (topo + tamanho) * mm, largura * mm, tamanho * mm, 5 * mm, fill=1, stroke=0)

    def paragrafo(texto, x, topo, largura, tamanho=29, negrito=False, cor=TINTA):
        estilo = ParagraphStyle('poster', fontName='Arial-Bold' if negrito else 'Arial',
                                fontSize=tamanho, leading=tamanho * 1.2, textColor=cor)
        p = Paragraph(texto, estilo)
        _, tamanho_real = p.wrap(largura * mm, altura)
        p.drawOn(pdf, x * mm, altura - topo * mm - tamanho_real)

    caixa(0, 0, 594, 841, colors.HexColor('#EDF4F1'))
    caixa(0, 0, 594, 176, VERDE)
    paragrafo('GEOMRIT 2027 · GEOINTELIGÊNCIA, SENSORIAMENTO REMOTO E INTELIGÊNCIA ARTIFICIAL',
              24, 17, 546, 23, True, colors.white)
    paragrafo(f'{escape(marca)}:', 24, 32, 546, 70, True, colors.white)
    paragrafo(escape(descricao), 24, 65, 415, 47, True, colors.white)
    paragrafo('Henrique Buzin', 24, 133, 546, 29, True, colors.white)
    paragrafo('Doutorado em Ciência da Computação / UFSC', 24, 150, 546, 25, cor=colors.white)

    caixa(22, 190, 550, 126, colors.white)
    paragrafo('Como prever onde o DETER registrará alertas no próximo trimestre?', 34, 201, 520, 32, True, VERDE)
    paragrafo('GEO-Detect usa duas camadas LSTM inspiradas em Kanoga et al. Células de 1,25 km no Pará e corte temporal um mês antes de cada trimestre.', 34, 238, 245, 27, True)
    paragrafo('Histórico do DETER, rede hidrográfica HydroRIVERS e localidades do IBGE. Avaliação do ranking completo pela precisão média (AP).', 307, 238, 245, 27)

    caixa(22, 331, 550, 292, colors.white)
    paragrafo('GEO-Detect e referências adaptadas', 34, 342, 520, 34, True, VERDE)
    paragrafo(f'AP: GEO-Detect {ap_geo}% · Larrea-Gallegos {ap_rf}% · Mayfield {ap_ann}%', 34, 366, 520, 34, True)
    paragrafo('629 alertas · seis trimestres · janeiro de 2024 a junho de 2025', 34, 389, 520, 27)
    figura = FIGURAS / 'fig_precisao_alertas.png'
    largura = 310
    tamanho = largura * proporcao(figura)
    pdf.drawImage(str(figura), 142 * mm, altura - (415 + tamanho) * mm,
                  width=largura * mm, height=tamanho * mm)

    caixa(22, 638, 550, 115, VERDE)
    paragrafo('Relação com a literatura', 34, 651, 520, 35, True, colors.white)
    paragrafo('Larrea-Gallegos: Random Forest e expansão da mineração.<br/>Kanoga (IEEE): LSTM e previsão de desmatamento.<br/>Mayfield: rede densa com uma camada oculta.', 34, 678, 520, 24, cor=colors.white)
    paragrafo('A figura compara as adaptações no mesmo protocolo retrospectivo do GEO-Detect.', 34, 727, 520, 21, cor=colors.white)
    paragrafo('Resultados retrospectivos no Pará. Figura de elaboração própria com DETER/INPE, HydroRIVERS e IBGE.', 24, 768, 546, 21)
    paragrafo('Referências · Larrea-Gallegos et al. (2023), doi:10.1016/j.cscee.2023.100353<br/>'
              'Kanoga et al. (2024), doi:10.1109/IGARSS53475.2024.10642628 · Mayfield et al. (2020), doi:10.1016/j.envsoft.2020.104741',
              24, 784, 546, 19)
    paragrafo('<link href="https://github.com/HenriqueBuzin/GEO-Detect"><u>github.com/HenriqueBuzin/GEO-Detect</u></link>', 24, 812, 546, 23, True, VERDE)
    pdf.save()


if __name__ == '__main__':
    SAIDA.mkdir(parents=True, exist_ok=True)
    for nome, arquivo in (('Arial', 'Arial.ttf'), ('Arial-Bold', 'Arial Bold.ttf'), ('Arial-Italic', 'Arial Italic.ttf')):
        pdfmetrics.registerFont(TTFont(nome, str(FONTE / arquivo)))
    pdfmetrics.registerFontFamily('Arial', normal='Arial', bold='Arial-Bold', italic='Arial-Italic', boldItalic='Arial-Bold')
    gerar_a4('resumo_expandido')
    gerar_poster()
