import os
import re
import wave
import asyncio
import subprocess
from pathlib import Path
import streamlit as st
import requests
from dotenv import dotenv_values
import gradium.client

# ==============================================================================
# CONFIGURAÇÃO GERAL E ESTILO (UX-LAWS & ZERO-FRICTION)
# ==============================================================================
st.set_page_config(
    page_title="RH Explica - Estudio de Video 16:9 & Narracao",
    page_icon="🎬",
    layout="wide",
    initial_sidebar_state="collapsed"
)

st.markdown("""
<style>
    .main .block-container { padding-top: 1.2rem; padding-bottom: 2rem; }
    .stButton button { border-radius: 8px; font-weight: 600; }
    .stTabs [data-baseweb="tab-list"] { gap: 12px; }
    .stTabs [data-baseweb="tab"] { border-radius: 8px; padding: 8px 16px; font-weight: 600; }
</style>
""", unsafe_allow_html=True)

BASE_DIR = Path(__file__).resolve().parent
VOZES_DIR = BASE_DIR / "PERSONAGENS" / "VOZES CLONADAS"
NARRATION_DIR = BASE_DIR / "NARRAÇÕES"
VIDEOS_GERADOS_DIR = BASE_DIR / "VIDEOS GERADOS"
LOGO_FILE = BASE_DIR / "LOGO PARA USO.png"

NARRATION_DIR.mkdir(parents=True, exist_ok=True)
VIDEOS_GERADOS_DIR.mkdir(parents=True, exist_ok=True)

# Suporte transparente a st.secrets (Streamlit Cloud) e .env (Local)
env_cfg = {}
try:
    if hasattr(st, "secrets"):
        for k, v in st.secrets.items():
            env_cfg[k] = str(v)
except Exception:
    pass
env_cfg.update(dotenv_values(BASE_DIR / ".env"))

GRADIUM_KEY = env_cfg.get("GRADIUM_API_KEY", "")
OPENROUTER_KEY = env_cfg.get("API_KEY_OPENROUTER", "")
OPENROUTER_MODEL = env_cfg.get("MODEL_USE", "fish-audio/s2.1-pro-free:free")

VOZES_MAP = {
    "ANA RH": {"id": env_cfg.get("ANA", "9mWFpgPdQZOr90Ys"), "genero": "f", "pasta": "ANA"},
    "HELDER RH": {"id": env_cfg.get("HELDER", "MRuyuP9Dsu3tYygv"), "genero": "m", "pasta": "HELDER"},
    "LUCAS RH": {"id": env_cfg.get("LUCAS", "svI9wjFfEHLGe2IR"), "genero": "m", "pasta": "LUCAS RH"},
    "THACIA": {"id": env_cfg.get("THACIA", "keek5swmJR4zK0Ir"), "genero": "f", "pasta": "THACIA"},
    "VALERIA RH": {"id": env_cfg.get("VALERIA", "XNjkL2rYUo7qydV3"), "genero": "f", "pasta": "VALERIA"},
    "LUCIANA RH": {"id": env_cfg.get("LUCIANA", "xCHbkhAKWvMl5LDP"), "genero": "f", "pasta": "LUCIANA"},
}

# ==============================================================================
# HIGIENIZAÇÃO DE TEXTO
# ==============================================================================
def sanitizar_nome_arquivo(nome: str) -> str:
    limpo = re.sub(r'[\\/*?:"<>|]', '', nome)
    return re.sub(r'\s+', ' ', limpo).strip()

def limpar_texto_para_fala(texto: str) -> str:
    t = re.sub(r'\[cite:[^\]]*\]', '', texto, flags=re.IGNORECASE)
    t = re.sub(r'[*#_`~]', '', t)
    t = re.sub(r'^-{3,}\s*$', '', t, flags=re.MULTILINE)
    linhas = [ln.strip() for ln in t.splitlines() if ln.strip()]
    return '\n\n'.join(linhas)

def analisar_roteiro_em_temas(texto_bruto: str):
    blocos_brutos = re.split(r'\n\s*---\s*\n', texto_bruto)
    temas = []
    for bloco in blocos_brutos:
        bloco = bloco.strip()
        if not bloco:
            continue
        match_titulo = re.search(r'^(?:#+\s*)?(Tema\s*\d+\s*[-–—]?\s*[^\n\r?]+(?:\?)?)', bloco, re.IGNORECASE | re.MULTILINE)
        if match_titulo:
            titulo_completo = match_titulo.group(1).strip()
            corpo_bruto = bloco[match_titulo.end(0):].strip()
            nome_sugerido = sanitizar_nome_arquivo(titulo_completo)
        else:
            primeira_linha = bloco.splitlines()[0][:60]
            titulo_completo = primeira_linha
            nome_sugerido = sanitizar_nome_arquivo(primeira_linha)
            corpo_bruto = bloco
            
        fala_limpa = limpar_texto_para_fala(corpo_bruto)
        if fala_limpa:
            temas.append({
                "titulo": titulo_completo,
                "nome_sugerido": nome_sugerido,
                "fala": fala_limpa
            })
    return temas

# ==============================================================================
# SÍNTESE DE ÁUDIO
# ==============================================================================
async def sintetizar_gradium(texto: str, voice_id: str, destino: Path) -> Path:
    client = gradium.client.GradiumClient(api_key=GRADIUM_KEY)
    result = await client.tts(
        setup={"voice_id": voice_id, "output_format": "wav"},
        text=texto
    )
    destino_wav = destino.with_suffix('.wav')
    destino_wav.write_bytes(result.raw_data)
    return destino_wav

async def sintetizar_edge_tts(texto: str, genero: str, destino: Path) -> Path:
    import edge_tts
    voice = "pt-BR-AntonioNeural" if genero == "m" else "pt-BR-FranciscaNeural"
    destino_mp3 = destino.with_suffix('.mp3')
    communicate = edge_tts.Communicate(texto, voice)
    await communicate.save(str(destino_mp3))
    return destino_mp3

# ==============================================================================
# COMPOSIÇÃO DE VÍDEO (FFMPEG - 1 TEMA = 1 CENA EM LOOP 16:9 WIDESCREEN)
# ==============================================================================
def renderizar_video_tema(caminho_video_base: Path, caminho_audio: Path, destino_mp4: Path, logo_path: Path) -> bool:
    # 16:9 Widescreen (1920x1080) nativo dos takes Veo 3
    cmd = [
        'ffmpeg', '-y',
        '-stream_loop', '-1', '-i', str(caminho_video_base),
        '-i', str(caminho_audio),
        '-i', str(logo_path),
        '-filter_complex',
        '[0:v]scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2,format=yuv420p[vid];'
        '[2:v]scale=200:-1[lg];'
        '[vid][lg]overlay=W-w-60:50[outv]',
        '-map', '[outv]',
        '-map', '1:a',
        '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '20',
        '-c:a', 'aac', '-b:a', '192k',
        '-shortest',
        str(destino_mp4)
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace')
    return res.returncode == 0

# ==============================================================================
# INTERFACE PRINCIPAL
# ==============================================================================
st.title("🎬 Estúdio RH Explica - Narração & Vídeo 16:9")

tab_audio, tab_video, tab_biblioteca = st.tabs([
    "🎙️ 1. Gerador de Narrações (Gradium)",
    "⚡ 2. Compositor de Vídeos 16:9 (Sem CapCut)",
    "📁 3. Biblioteca de Arquivos"
])

# ------------------------------------------------------------------------------
# ABA 1: GERADOR DE NARRAÇÕES
# ------------------------------------------------------------------------------
with tab_audio:
    col_setup, col_exec = st.columns([1, 2], gap="large")
    
    with col_setup:
        st.subheader("1. Personagem e Voz")
        nomes_disponiveis = list(VOZES_MAP.keys())
        personagem_escolhido = st.selectbox("Selecione o Personagem:", nomes_disponiveis, index=0, key="sel_audio_pers")
        
        dados_voz = VOZES_MAP[personagem_escolhido]
        voice_id_ativo = dados_voz["id"]
        st.markdown(f"**Gradium Voice ID:** `{voice_id_ativo}`")
        
        arquivo_amostra = VOZES_DIR / f"{personagem_escolhido}.ogg"
        if not arquivo_amostra.exists():
            arquivo_amostra = VOZES_DIR / f"{personagem_escolhido.replace(' RH', '')}.ogg"
        if arquivo_amostra.exists():
            st.caption("Amostra Original de Referência:")
            st.audio(str(arquivo_amostra))

        st.markdown("---")
        st.subheader("2. Motor")
        motor = st.radio(
            "Motor de Síntese:",
            [
                "Gradium API (Oficial / Single-Take Otimizado)",
                "Local Neural (Edge-TTS / Rascunho Grátis)"
            ],
            key="sel_motor_audio"
        )
        prefixar_pers = st.checkbox("Incluir nome do personagem no arquivo", value=False, key="check_prefix_audio")

    with col_exec:
        st.subheader("3. Roteiro")
        roteiro_input = st.text_area(
            "Cole aqui o roteiro de temas:",
            height=200,
            placeholder="### Tema 19 - Quais são os exames ocupacionais obrigatórios?\n\nOlá! Eu sou a Ana...",
            key="area_roteiro"
        )
        
        temas = analisar_roteiro_em_temas(roteiro_input) if roteiro_input.strip() else []
        
        if temas:
            st.markdown(f"**Temas detectados:** `{len(temas)}`")
            modo_geracao = st.radio("Modo:", ["Gerar Tema Selecionado", "Gerar Todos em Lote (Batch)"], horizontal=True, key="modo_audio")
            
            if modo_geracao == "Gerar Tema Selecionado":
                labels_temas = [f"{i+1}. {t['titulo']}" for i, t in enumerate(temas)]
                sel_idx = st.selectbox("Tema:", range(len(labels_temas)), format_func=lambda x: labels_temas[x], key="sel_tema_idx")
                tema_atual = temas[sel_idx]
                
                nome_sugerido = tema_atual["nome_sugerido"]
                if prefixar_pers:
                    prefixo = personagem_escolhido.replace(" RH", "").upper()
                    nome_sugerido = f"{prefixo} - {nome_sugerido}"
                    
                nome_final = st.text_input("Nome do Arquivo:", value=nome_sugerido, key="input_nome_arq")
                
                with st.expander("Ver texto higienizado a sintetizar:"):
                    st.write(tema_atual["fala"])
                
                if st.button("🎙️ Gerar Narração do Tema", type="primary", use_container_width=True, key="btn_gerar_single"):
                    destino_base = NARRATION_DIR / sanitizar_nome_arquivo(nome_final)
                    with st.spinner("Sintetizando áudio oficial com Gradium..."):
                        try:
                            if motor.startswith("Gradium"):
                                arq_salvo = asyncio.run(sintetizar_gradium(tema_atual["fala"], voice_id_ativo, destino_base))
                            else:
                                arq_salvo = asyncio.run(sintetizar_edge_tts(tema_atual["fala"], dados_voz["genero"], destino_base))
                            st.success(f"Narração salva com sucesso!")
                            st.audio(str(arq_salvo))
                        except Exception as e:
                            st.error(f"Erro: {str(e)}")
            else:
                st.warning(f"Serão gerados {len(temas)} áudios em lote.")
                if st.button(f"⚡ Gerar {len(temas)} Temas em Lote", type="primary", use_container_width=True, key="btn_gerar_batch"):
                    barra = st.progress(0)
                    for i, t in enumerate(temas):
                        nome_arq = t["nome_sugerido"]
                        if prefixar_pers:
                            prefixo = personagem_escolhido.replace(" RH", "").upper()
                            nome_arq = f"{prefixo} - {nome_arq}"
                        destino_base = NARRATION_DIR / sanitizar_nome_arquivo(nome_arq)
                        try:
                            if motor.startswith("Gradium"):
                                asyncio.run(sintetizar_gradium(t["fala"], voice_id_ativo, destino_base))
                            else:
                                asyncio.run(sintetizar_edge_tts(t["fala"], dados_voz["genero"], destino_base))
                        except Exception as err:
                            st.error(f"Erro em {nome_arq}: {err}")
                        barra.progress((i + 1) / len(temas))
                    st.success("Lote concluído com sucesso!")

# ------------------------------------------------------------------------------
# ABA 2: COMPOSITOR DE VÍDEOS AUTOMÁTICO (16:9 WIDESCREEN)
# ------------------------------------------------------------------------------
with tab_video:
    st.subheader("Montagem Automatizada de Vídeos 16:9 (1920x1080)")
    st.caption("Aplica 1 cena exclusiva em loop contínuo widescreen, preservando 100% do cenário do Veo 3 sem cortes, com o logo e áudio perfeitamente integrados.")
    
    col_v1, col_v2 = st.columns([1, 2], gap="large")
    
    with col_v1:
        st.markdown("### 1. Parâmetros do Vídeo")
        pers_video = st.selectbox("Personagem para o Vídeo:", list(VOZES_MAP.keys()), index=0, key="sel_video_pers")
        pasta_pers = BASE_DIR / "PERSONAGENS" / VOZES_MAP[pers_video]["pasta"]
        
        videos_cena = sorted(list(pasta_pers.glob("*HRZ*.mp4")) + list(pasta_pers.glob("*VIDEO*.mp4")))
        if not videos_cena:
            st.error(f"Nenhum vídeo HRZ encontrado na pasta {pasta_pers}")
            cena_escolhida = None
        else:
            rotulos_cena = [v.name for v in videos_cena]
            idx_cena = st.selectbox("Cena Exclusiva (1 Tema = 1 Cena):", range(len(rotulos_cena)), format_func=lambda x: rotulos_cena[x])
            cena_escolhida = videos_cena[idx_cena]
            st.caption(f"Arquivo selecionado: `{cena_escolhida.name}`")
            
        st.markdown("---")
        st.markdown("### 2. Formato e Identidade")
        st.success("📐 Formato Padrão: **16:9 Widescreen (1920x1080 Full HD)**")
        st.checkbox("Aplicar Logo Oficial", value=True, disabled=True)
        st.caption(f"Logo ativo: `{LOGO_FILE.name}`")
        st.info("💡 Slots para Boxname e Encerramento Padrão preservados.")

    with col_v2:
        st.markdown("### 3. Seleção de Áudio e Renderização")
        audios_disponiveis = sorted(list(NARRATION_DIR.glob("*.wav")) + list(NARRATION_DIR.glob("*.mp3")), key=lambda x: x.stat().st_mtime, reverse=True)
        
        if not audios_disponiveis:
            st.warning("Nenhum áudio encontrado na pasta NARRAÇÕES/. Gere primeiro um áudio na Aba 1.")
        else:
            rotulos_audios = [f"{a.name} ({a.stat().st_size / 1024:.1f} KB)" for a in audios_disponiveis]
            idx_audio = st.selectbox("Selecione a Narração do Tema:", range(len(rotulos_audios)), format_func=lambda x: rotulos_audios[x], key="sel_audio_para_video")
            audio_escolhido = audios_disponiveis[idx_audio]
            
            nome_sug_video = audio_escolhido.stem
            nome_video_saida = st.text_input("Nome do Vídeo Final (sem extensão):", value=nome_sug_video, key="nome_video_saida")
            
            st.audio(str(audio_escolhido))
            
            btn_render_video = st.button("⚡ Renderizar Vídeo 16:9 (1 Clique)", type="primary", use_container_width=True, key="btn_render_v")
            
            if btn_render_video and cena_escolhida:
                destino_video = VIDEOS_GERADOS_DIR / f"{sanitizar_nome_arquivo(nome_video_saida)}.mp4"
                with st.spinner("Processando montagem do vídeo 16:9 com FFmpeg (1920x1080 + Loop + Logo)..."):
                    sucesso = renderizar_video_tema(cena_escolhida, audio_escolhido, destino_video, LOGO_FILE)
                    if sucesso:
                        st.success(f"Vídeo 16:9 renderizado com sucesso em {destino_video.name}!")
                        st.video(str(destino_video))
                        st.caption(f"📁 Salvo em: `{destino_video.relative_to(BASE_DIR)}`")
                    else:
                        st.error("Erro na renderização via FFmpeg.")

# ------------------------------------------------------------------------------
# ABA 3: BIBLIOTECA DE ARQUIVOS
# ------------------------------------------------------------------------------
with tab_biblioteca:
    st.subheader("📁 Arquivos Concluídos")
    
    col_b1, col_b2 = st.columns(2)
    
    with col_b1:
        st.markdown("#### Narrações Recentes (`NARRAÇÕES/`)")
        audios_lib = sorted(list(NARRATION_DIR.glob("*.wav")) + list(NARRATION_DIR.glob("*.mp3")), key=lambda x: x.stat().st_mtime, reverse=True)
        for a in audios_lib[:6]:
            with st.container(border=True):
                st.markdown(f"**{a.name}**")
                st.caption(f"Tamanho: {a.stat().st_size / (1024 * 1024):.2f} MB")
                st.audio(str(a))
                
    with col_b2:
        st.markdown("#### Vídeos Renderizados (`VIDEOS GERADOS/`)")
        videos_lib = sorted(list(VIDEOS_GERADOS_DIR.glob("*.mp4")), key=lambda x: x.stat().st_mtime, reverse=True)
        for v in videos_lib[:4]:
            with st.container(border=True):
                st.markdown(f"**{v.name}**")
                st.caption(f"Tamanho: {v.stat().st_size / (1024 * 1024):.2f} MB")
                st.video(str(v))
