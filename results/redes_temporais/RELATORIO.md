# Comparação com referências publicadas

| Método avaliado na tarefa GEO-Detect | Precisão média |
|---|---:|
| GEO-Detect, LSTM inspirada em Kanoga et al. | 1,36% |
| Random Forest de Larrea-Gallegos et al., adaptada | 1,29% |
| Rede densa de Mayfield et al., adaptada | 1,14% |

São 629 alertas em seis trimestres retrospectivos do Pará. A AP usa o ranking completo. Os três métodos usam DETER, HydroRIVERS e IBGE. A rede densa conserva uma camada oculta de 60 unidades do estudo de Mayfield e usa o protocolo comum de treino da LSTM. A comparação numérica diz respeito às adaptações neste conjunto de dados.

## Diagnóstico do GEO-Detect por histórico

| Célula | Pares célula-trimestre positivos | AP dentro do grupo |
|---|---:|---:|
| Com alerta anterior | 182 | 2,63% |
| Sem alerta anterior | 390 | 0,91% |

Os valores por grupo usam universos e prevalências diferentes e não se somam à AP global. A LSTM reproduziu a execução anterior nas seis origens. Ver [dados por origem](por_origem.csv), [dados por histórico](por_historico.csv) e [dados por origem da Random Forest](../multiescala/bases_por_origem.csv).

## Reprodução

Com as [fontes congeladas](../multiescala/FONTES.md) e PyTorch 2.15.0, execute `python scripts/25_mayfield_alertas.py`. Os hashes são verificados contra os da execução original da LSTM.
