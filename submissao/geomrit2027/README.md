# Artigo e materiais da GEOMRIT 2027

**GEO-Detect: uma rede neural para previsão espacial de alertas de mineração na Amazônia**

- [Artigo completo, formato IEEE](../../output/pdf/artigo_ieee.pdf) · [Fonte LaTeX](artigo_ieee.tex).
- [Resumo expandido para submissão](../../output/pdf/resumo_expandido.pdf) · [Fonte editável](resumo_expandido.md). Três páginas A4 com referências.
- [Pôster preliminar](../../output/pdf/poster_preliminar.pdf). A1 vertical como prova provisória.
- [Plano científico](PLANO_PESQUISA.md) · [Trabalhos relacionados](trabalhos_relacionados.md).

O [pacote de reprodução](../../output/reproducao/geodetect-reproducao.zip) acompanha o artigo. O [guia](../../reproducao/README.md) indica como instalar as dependências, validar as fontes e recalcular a figura.

Para compilar o artigo na raiz do repositório com Tectonic:

```sh
tectonic --outdir "$(pwd)/output/pdf" submissao/geomrit2027/artigo_ieee.tex
```

O gerador [`gerar_pdfs.py`](gerar_pdfs.py) gera o resumo e o pôster. Requer Python com ReportLab e Pillow e usa as fontes Arial do macOS.
