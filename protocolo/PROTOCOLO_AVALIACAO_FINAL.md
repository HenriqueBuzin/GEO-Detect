# Protocolo da avaliação final — GEO-Detect v1.0

**Congelado em:** 10/11/2026, na branch `feature/hexagonal-h3`, **antes** de qualquer leitura espacial dos alertas-alvo do teste.
**Especificação executável:** [`protocolo_avaliacao_final.json`](protocolo_avaliacao_final.json), lida por `scripts/07_final_evaluation.py`.
**Prova de pré-registro:** o protocolo e o código entram num commit anterior ao commit que contém os resultados.
O script grava o hash desse commit e o SHA-256 do protocolo na saída.

## 1. Pergunta confirmatória (P1)

Sob o mesmo orçamento territorial (2% da área do universo), a configuração **H3 resolução 7 + vizinhança**
captura uma fração maior dos alertas de mineração do trimestre seguinte do que o **quadrado de 2,5 km + vizinhança**?

Só P1 é confirmatória. Todo o resto é descritivo:
- S1 e S2: ganho da vizinhança em cada grade.
- S3 e S4: comparação com a referência original (quadrado de 5 km, contagem).
- Os orçamentos de 1% e 5%.
- As origens semi-independentes.

## 2. Configuração congelada

| Item | Valor |
|---|---|
| Dados | `deter_amz_mineracao_pa.geojson`, SHA-256 `b4b4224a…cc8e4d1`, DETER atualizado em 30/10/2026. **Não rebaixar.** |
| Preparo | `geodetect/dados.py`: `make_valid` antes e depois da projeção, remoção de fragmentos < 0,1 ha, ESRI:102033 |
| Grade principal | H3 resolução 7 (célula média de 5,67 km² na região) |
| Controle geométrico | quadrado de 2,5 km (6,25 km²) |
| Referência original | quadrado de 5 km, contagem de 24 meses (A_24m, congelado no script 03) |
| Pontuação A | nº de alertas (centroide) na célula com `view_date` em [corte − 24 meses, corte) |
| Pontuação C | A + **0,5** · média de A nos vizinhos imediatos (6 no H3; 8 no quadrado). w = 0,5 foi escolhido nas origens 2024-01, 04 e 07 nas duas grades |
| Desempate | expectativa sob desempate aleatório |
| Corte de informação | origem − 1 mês (o DETER público não informa a data de publicação) |
| Alvo | alertas em [origem, origem + 3 meses) |
| Universo | quadrados de 5 km a até 10 km de algum alerta disponível; em cada grade, as células com centro nesses quadrados |
| Orçamentos | 1%, **2% (primário)** e 5% da área de referência (25 km² × nº de quadrados do universo) |
| k | max(1, round(fração · área de referência / área média das células da grade no universo)) |
| **Métrica primária** | **Recall@B**: alertas-alvo (centroide) dentro das células selecionadas ÷ total de alertas-alvo |

O Recall@B é definido sobre **alertas**, não sobre células. O recall por células depende do tamanho da célula e não é
comparável entre grades. Ele é reportado apenas como métrica secundária, dentro de cada grade.

## 3. Quais origens são teste de verdade

| Período dos alvos | Origens | Exposição anterior | Classificação |
|---|---|---|---|
| jan/2024 – jun/2025 | 2024-01 … 2025-04 | Usado para escolher janelas, w, grade e resolução | **Desenvolvimento** |
| jul – dez/2025 | 2025-07, 2025-10 | A auditoria mostrou contagens mensais, mapa dos centroides, distribuição por município e, sobretudo, a cobertura espacial (96,9%) que motivou o raio de 10 km do universo | **Semi-independente**: reportado à parte, **não** é teste intocado |
| jan – set/2026 | 2026-01, 2026-04, 2026-07 | Apenas o total anual de 2026 (556 alertas, 363 células, até 28/10). Nenhuma informação mensal ou espacial | **Teste independente**: base da conclusão |

Risco conhecido: os meses mais recentes, em particular jul–set/2026, podem ainda ser revisados pelo INPE depois de 30/10/2026.

## 4. Estatística e regra de decisão

- **Estimativa:** recall agregado do grupo de origens (alertas capturados ÷ alertas-alvo, somando as origens), além dos valores por origem.
- **Incerteza:** bootstrap espacial em blocos.
  - Cada bloco é um par (origem, quadrado de 5 km do centroide do alerta-alvo).
  - Os blocos são reamostrados com reposição dentro de cada origem: 2.000 réplicas, semente 2027.
  - O intervalo é o percentil de 95% da diferença pareada.
  - Blocos espaciais reduzem, mas não eliminam, a dependência entre alertas próximos.
- **Decisão P1, com orçamento de 2% e só as origens independentes:**
  - IC 95% de (H3 r7 + C) − (quadrado 2,5 km + C) **todo acima de 0** → "H3 superior ao controle".
  - **Todo abaixo de 0** → "H3 inferior ao controle".
  - Caso contrário → "**inconclusivo**": sem evidência de diferença com 3 origens.
- **Proibições:**
  - Mudar parâmetros, grades, modelos, origens, orçamentos ou métrica depois de ver o resultado.
  - Rodar de novo para escolher um resultado: o script recusa sobrescrever a saída.
  - Rebaixar os dados.

## 5. Resultados exploratórios que motivaram a escolha

Todos são do desenvolvimento, com 6 origens ([`results/hexagonal/RELATORIO.md`](../results/hexagonal/RELATORIO.md)).
Os valores são o recall de alertas com 2% da área.

| Grade | A | C* |
|---|---|---|
| quadrado 5 km | 0,210 | 0,216 |
| quadrado 2,5 km | 0,236 | 0,245 |
| **H3 r7** | **0,275** | **0,311** |
| quadrado 1 km | 0,168 | 0,283 |
| H3 r8 | 0,118 | 0,298 |

Diferença pareada entre H3 r7 e o quadrado de 2,5 km, por modelo: A +0,039 (5/6), C* +0,066 (5/6), D* +0,038 (6/6).
Entre H3 r8 e o quadrado de 1 km não houve diferença.

Por que H3 r7 e não outra opção:
- Teve o maior recall com vizinhança e a maior estabilidade (Jaccard 0,79).
- O par de controle com área parecida existe (quadrado de 2,5 km).
- A resolução de cerca de 6 km² também foi a melhor para os quadrados.

O modelo D (atividade recente dos vizinhos) foi **descartado**, porque não teve ganho consistente entre grades.

**Viés esperado:** como a grade foi escolhida por ser a melhor no desenvolvimento, é provável que o desempenho no
teste fique **abaixo** do observado no desenvolvimento (regressão à média). A comparação P1 é menos afetada,
porque o controle também foi escolhido com o mesmo critério e na mesma resolução.

### Validação do pipeline final no desenvolvimento (antes de abrir o teste)

Ao rodar `07_final_evaluation.py --modo dev`, o pipeline **reproduz exatamente** o script 05: 90 de 90 linhas, diferença zero.
Com a estatística deste protocolo (recall agregado e bootstrap espacial), os resultados no desenvolvimento são:

| Comparação (2%) | Diferença | IC 95% | Veredito no desenvolvimento |
|---|---|---|---|
| P1 H3 r7 + C − quadrado 2,5 km + C | +0,024 | [−0,004; +0,053] | inconclusivo |
| S1 H3 r7: C − A | +0,015 | [−0,002; +0,031] | inconclusivo |
| S2 quadrado 2,5 km: C − A | +0,017 | [+0,001; +0,034] | superior |
| S3 H3 r7 + C − quadrado 5 km A | +0,077 | [+0,041; +0,114] | superior |
| S4 quadrado 2,5 km + C − quadrado 5 km A | +0,054 | [+0,019; +0,088] | superior |

A média por origem (+0,066 em P1) superestimava a diferença, porque dava o mesmo peso a trimestres com 19 e com 276 alertas.
**Já no desenvolvimento, a vantagem do hexágono não se sustenta com a estatística pré-especificada.** A expectativa
registrada antes do teste é, portanto, um P1 **inconclusivo** e S3/S4 positivos.

## 6. Verificações obrigatórias, registradas na saída

1. SHA-256 dos dados igual ao do protocolo.
2. Protocolo, `geodetect/` e o script final sem alterações em relação ao último commit.
3. Nenhum alerta usado como informação tem `view_date` ≥ corte da origem (o código falha se houver).
4. Área do universo de cada grade ÷ área de referência, por origem.
5. Área efetivamente selecionada (esperada) ÷ orçamento, por grade e orçamento.
6. Validação prévia: no modo `dev`, o script reproduz os números do script 05 nas origens de desenvolvimento, sem ler o teste.
