import os
import re
import wave
import asyncio
import subprocess
from pathlib import Path
import streamlit as st
import requests
from dotenv import dotenv_values
from PIL import Image, ImageDraw, ImageFont
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
ENCERRAMENTO_FILE = BASE_DIR / "ENCERRAMENTO PADRÃO.mp4"
TEMP_DIR = BASE_DIR / ".temp"

NARRATION_DIR.mkdir(parents=True, exist_ok=True)
VIDEOS_GERADOS_DIR.mkdir(parents=True, exist_ok=True)
TEMP_DIR.mkdir(parents=True, exist_ok=True)

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

VOZES_MAP = {
    "ANA RH": {"id": env_cfg.get("ANA", "9mWFpgPdQZOr90Ys"), "genero": "f", "pasta": "ANA"},
    "HELDER RH": {"id": env_cfg.get("HELDER", "MRuyuP9Dsu3tYygv"), "genero": "m", "pasta": "HELDER"},
    "LUCAS RH": {"id": env_cfg.get("LUCAS", "svI9wjFfEHLGe2IR"), "genero": "m", "pasta": "LUCAS RH"},
    "THACIA": {"id": env_cfg.get("THACIA", "keek5swmJR4zK0Ir"), "genero": "f", "pasta": "THACIA"},
    "VALERIA RH": {"id": env_cfg.get("VALERIA", "XNjkL2rYUo7qydV3"), "genero": "f", "pasta": "VALERIA"},
    "LUCIANA RH": {"id": env_cfg.get("LUCIANA", "xCHbkhAKWvMl5LDP"), "genero": "f", "pasta": "LUCIANA"},
}

# ==============================================================================
# HIGIENIZAÇÃO DE TEXTO E UTILITÁRIOS
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

def obter_duracao_midia(caminho: Path) -> float:
    cmd = ['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1', str(caminho)]
    try:
        res = subprocess.check_output(cmd, text=True).strip()
        return float(res)
    except Exception:
        return 0.0

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
# CARD H1 (DESIGN VISUAL COM PILLOW PARA 16:9 WIDESCREEN)
# ==============================================================================
def gerar_card_h1(titulo: str, destino_png: Path, largura: int = 1920, altura: int = 1080) -> Path:
    img = Image.new('RGBA', (largura, altura), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    
    # Fontes com fallback
    font_badge = None
    font_titulo = None
    for fonte in ["segoeuib.ttf", "arialbd.ttf", "DejaVuSans-Bold.ttf"]:
        try:
            font_badge = ImageFont.truetype(fonte, 20)
            font_titulo = ImageFont.truetype(fonte, 38)
            break
        except Exception:
            pass
    if font_badge is None:
        font_badge = ImageFont.load_default()
        font_titulo = ImageFont.load_default()

    texto = titulo.strip()
    badge_texto = "RH EXPLICA"

    bbox_badge = draw.textbbox((0, 0), badge_texto, font=font_badge)
    bbox_tit = draw.textbbox((0, 0), texto, font=font_titulo)
    
    w_conteudo = max(bbox_badge[2] - bbox_badge[0], bbox_tit[2] - bbox_tit[0])
    h_conteudo = (bbox_badge[3] - bbox_badge[1]) + (bbox_tit[3] - bbox_tit[1]) + 18

    pad_x, pad_y = 36, 22
    box_w = min(w_conteudo + (pad_x * 2), largura - 160)
    box_h = h_conteudo + (pad_y * 2)

    box_x = 80
    box_y = 60

    # Container escuro fosco translúcido com borda suave
    draw.rounded_rectangle(
        [box_x, box_y, box_x + box_w, box_y + box_h],
        radius=14,
        fill=(15, 23, 42, 215),
        outline=(255, 255, 255, 45),
        width=2
    )

    # Tag / Badge
    draw.text((box_x + pad_x, box_y + pad_y), badge_texto, fill=(56, 189, 248, 255), font=font_badge)
    # Título H1
    draw.text((box_x + pad_x, box_y + pad_y + (bbox_badge[3] - bbox_badge[1]) + 10), texto, fill=(255, 255, 255, 255), font=font_titulo)

    destino_png.parent.mkdir(parents=True, exist_ok=True)
    img.save(destino_png, "PNG")
    return destino_png

# ==============================================================================
# COMPOSIÇÃO DE VÍDEO (FFMPEG - 16:9 WIDESCREEN + H1 + ENCERRAMENTO PADRÃO)
# ==============================================================================
def renderizar_video_tema(
    caminho_video_base: Path,
    caminho_audio: Path,
    destino_mp4: Path,
    logo_path: Path,
    titulo_h1: str = "",
    incluir_encerramento: bool = True
) -> bool:
    audio_dur = obter_duracao_midia(caminho_audio)
    if audio_dur <= 0:
        return False

    temp_card = TEMP_DIR / f"card_{sanitizar_nome_arquivo(titulo_h1 or 'h1')}.png"
    usar_h1 = bool(titulo_h1.strip())
    if usar_h1:
        gerar_card_h1(titulo_h1.strip(), temp_card)

    has_encerramento = incluir_encerramento and ENCERRAMENTO_FILE.exists()

    input_args = []
    
    # 0: Vídeo base em loop contínuo
    input_args.extend(['-stream_loop', '-1', '-i', str(caminho_video_base)])
    
    # 1: Áudio narrado oficial
    input_args.extend(['-i', str(caminho_audio)])
    
    # 2: Logo oficial
    input_args.extend(['-i', str(logo_path)])
    
    next_idx = 3
    idx_card = None
    if usar_h1:
        input_args.extend(['-i', str(temp_card)])
        idx_card = next_idx
        next_idx += 1

    idx_enc = None
    idx_sil = None
    if has_encerramento:
        input_args.extend(['-i', str(ENCERRAMENTO_FILE)])
        idx_enc = next_idx
        next_idx += 1
        input_args.extend(['-f', 'lavfi', '-t', '16', '-i', 'anullsrc=r=44100:cl=stereo'])
        idx_sil = next_idx
        next_idx += 1

    filter_chains = [
        f'[0:v]scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2,format=yuv420p,fps=30,trim=duration={audio_dur}[vbase]',
        '[2:v]scale=200:-1[lg]',
        '[vbase][lg]overlay=W-w-60:50[vlogo]'
    ]

    curr_v = 'vlogo'
    if usar_h1 and idx_card is not None:
        filter_chains.append(f'[{idx_card}:v]fade=t=in:st=0:d=0.5:alpha=1,fade=t=out:st=6.5:d=0.8:alpha=1[h1card]')
        filter_chains.append(f'[{curr_v}][h1card]overlay=0:0[vwithh1]')
        curr_v = 'vwithh1'

    filter_chains.append(f'[1:a]aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=stereo,atrim=duration={audio_dur}[ap1]')

    if has_encerramento and idx_enc is not None and idx_sil is not None:
        filter_chains.extend([
            f'[{idx_enc}:v]scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2,format=yuv420p,fps=30[venc]',
            f'[{idx_sil}:a]aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=stereo[aenc]',
            f'[{curr_v}][ap1][venc][aenc]concat=n=2:v=1:a=1[outv][outa]'
        ])
        map_v, map_a = '[outv]', '[outa]'
    else:
        map_v, map_a = f'[{curr_v}]', '[ap1]'

    cmd = [
        'ffmpeg', '-y',
        *input_args,
        '-filter_complex', ';'.join(filter_chains),
        '-map', map_v,
        '-map', map_a,
        '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '22',
        '-c:a', 'aac', '-b:a', '192k',
        str(destino_mp4)
    ]

    res = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace')
    if res.returncode != 0:
        print("FFMPEG ERROR:\n", res.stderr[-500:])
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
    st.subheader("Montagem Automatizada de Vídeos 16:9 (1920x1080 Full HD)")
    st.caption("Aplica 1 cena exclusiva em loop contínuo widescreen ou vídeo sincronizado do DreamFace, insere o Title Card H1 com fade-out, logo oficial e anexa o Encerramento Padrão automaticamente.")
    
    col_v1, col_v2 = st.columns([1, 2], gap="large")
    
    with col_v1:
        st.markdown("### 1. Personagem e Vídeo Base")
        pers_video = st.selectbox("Personagem:", list(VOZES_MAP.keys()), index=0, key="sel_video_pers")
        pasta_pers = BASE_DIR / "PERSONAGENS" / VOZES_MAP[pers_video]["pasta"]
        
        # Encontrar vídeos base (Veo 3 original ou já sincronizados no DreamFace)
        videos_cena = sorted(
            list(pasta_pers.glob("*HRZ*.mp4")) + 
            list(pasta_pers.glob("*VIDEO*.mp4")) +
            list(pasta_pers.glob("*DREAMFACE*.mp4")) +
            list(pasta_pers.glob("*LIP*.mp4"))
        )
        
        if not videos_cena:
            st.error(f"Nenhum vídeo HRZ encontrado na pasta {pasta_pers}")
            cena_escolhida = None
        else:
            rotulos_cena = [v.name for v in videos_cena]
            idx_cena = st.selectbox("Vídeo Base (1 Tema = 1 Cena):", range(len(rotulos_cena)), format_func=lambda x: rotulos_cena[x])
            cena_escolhida = videos_cena[idx_cena]
            st.caption(f"Cena ativa: `{cena_escolhida.name}`")
            
        st.markdown("---")
        st.markdown("### 2. Recursos de Acabamento")
        st.success("📐 Resolução: **1920x1080 (16:9 Full HD)**")
        
        chk_h1 = st.checkbox("🏷️ Inserir Card H1 do Tema (Fade-out aos 7s)", value=True, key="chk_h1")
        chk_encerramento = st.checkbox("🎬 Anexar Encerramento Padrão (16s)", value=True, key="chk_encerramento")
        
        if ENCERRAMENTO_FILE.exists():
            st.caption(f"Arquivo de encerramento: `{ENCERRAMENTO_FILE.name}`")
        else:
            st.warning("Arquivo 'ENCERRAMENTO PADRÃO.mp4' não encontrado na raiz.")

    with col_v2:
        st.markdown("### 3. Seleção de Áudio e Renderização")
        audios_disponiveis = sorted(list(NARRATION_DIR.glob("*.wav")) + list(NARRATION_DIR.glob("*.mp3")), key=lambda x: x.stat().st_mtime, reverse=True)
        
        if not audios_disponiveis:
            st.warning("Nenhum áudio encontrado na pasta NARRAÇÕES/. Gere primeiro um áudio na Aba 1.")
        else:
            rotulos_audios = [f"{a.name} ({a.stat().st_size / 1024:.1f} KB)" for a in audios_disponiveis]
            idx_audio = st.selectbox("Selecione a Narração do Tema:", range(len(rotulos_audios)), format_func=lambda x: rotulos_audios[x], key="sel_audio_para_video")
            audio_escolhido = audios_disponiveis[idx_audio]
            
            # Sugestão de título H1 e nome de arquivo
            titulo_h1_sugerido = audio_escolhido.stem
            nome_sug_video = f"{sanitizar_nome_arquivo(audio_escolhido.stem)}_16x9"
            
            titulo_h1_input = st.text_input("Título H1 para o Card em Vídeo:", value=titulo_h1_sugerido, key="input_h1_text")
            nome_video_saida = st.text_input("Nome do Arquivo de Saída:", value=nome_sug_video, key="nome_video_saida")
            
            st.audio(str(audio_escolhido))
            
            btn_render_video = st.button("⚡ Renderizar Vídeo 16:9 Completo (1 Clique)", type="primary", use_container_width=True, key="btn_render_v")
            
            if btn_render_video and cena_escolhida:
                destino_video = VIDEOS_GERADOS_DIR / f"{sanitizar_nome_arquivo(nome_video_saida)}.mp4"
                with st.spinner("Compondo vídeo 16:9 com FFmpeg (Overlay H1 + Loop + Logo + Encerramento Padrão)..."):
                    sucesso = renderizar_video_tema(
                        caminho_video_base=cena_escolhida,
                        caminho_audio=audio_escolhido,
                        destino_mp4=destino_video,
                        logo_path=LOGO_FILE,
                        titulo_h1=titulo_h1_input if chk_h1 else "",
                        incluir_encerramento=chk_encerramento
                    )
                    if sucesso:
                        st.success(f"Vídeo 16:9 renderizado com sucesso!")
                        st.video(str(destino_video))
                        st.caption(f"📁 Salvo em: `{destino_video.relative_to(BASE_DIR)}`")
                    else:
                        st.error("Erro na renderização via FFmpeg. Verifique os arquivos selecionados.")

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
