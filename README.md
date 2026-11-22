# RH Explica - Estúdio de Narração & Vídeo 16:9

Estúdio automatizado para geração de narrações otimizadas (Gradium API) e composição de vídeos em formato 16:9 (1920x1080 Full HD) para os personagens institucionais.

## Funcionalidades
- **Higienização de Roteiros**: Remoção automática de citações `[cite: ...]`, formatação markdown e normalização de texto para menor consumo de tokens.
- **Detecção de Múltiplos Temas**: Suporte a roteiros colados em lote com identificação automática de tópicos (`Tema XX`).
- **Geração Single-Take (Gradium API)**: Geração estrita de 1 output de áudio (formato WAV 48kHz) sem a duplicidade padrão do web app, economizando mais de 50% de créditos.
- **Compositor de Vídeo 16:9 (FFmpeg)**: Loop contínuo da cena do Veo 3, encaixe na duração exata do áudio e inclusão automática do logo oficial sem necessidade de edição manual no CapCut.

## Instalação e Execução
```bash
pip install -r requirements.txt
streamlit run app_narrador.py
```
