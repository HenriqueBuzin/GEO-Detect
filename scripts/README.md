# Código do experimento

| Script | Responsabilidade |
|---|---|
| [`01_download_deter.py`](01_download_deter.py) | Extrai alertas do WFS TerraBrasilis e registra metadados e hashes |
| [`23_bases_preditores.py`](23_bases_preditores.py) | Calcula distâncias geográficas e ajusta a Random Forest de referência |
| [`24_lstm_alertas.py`](24_lstm_alertas.py) | Monta séries mensais, ajusta a LSTM e mede AP a cada trimestre |
| [`25_mayfield_alertas.py`](25_mayfield_alertas.py) | Avalia a rede densa adaptada e diagnostica resultados por histórico |
| [`12_poster_figures.py`](12_poster_figures.py) | Gera a figura de precisão média do artigo |
| [`reproduzir_artigo.py`](reproduzir_artigo.py) | Verifica arquivos, executa o experimento e confere as métricas esperadas |

Os scripts 16 e 21 mantêm rotinas reutilizadas pela análise. O script 18 faz parte dos testes de regressão do protocolo anterior. Use o [guia de reprodução](../reproducao/README.md) para rodar a comparação do artigo.
