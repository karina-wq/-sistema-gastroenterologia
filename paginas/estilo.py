"""Apariencia de la aplicación: colores institucionales, logo, tarjetas y tablas con color por estado.

Todo lo visual está aquí; las pantallas solo llaman a estas funciones. Los colores salen del logo
del Hospital Nacional Arzobispo Loayza (azul y rojo)."""
import base64
from pathlib import Path

import pandas as pd
import streamlit as st

AZUL, AZUL_OSCURO, ROJO = "#1237C4", "#0B1F4D", "#D7263D"
VERDE, AMBAR, GRIS = "#1E9E6A", "#E39B0B", "#7C879C"
LOGO = Path(__file__).resolve().parent.parent / "assets" / "logo.png"

# Color de cada estado de cita (se usa en tablas y gráficos)
COLOR_ESTADO = {"asistio": VERDE, "programada": AZUL, "inasistio": ROJO, "reprogramada": AMBAR, "cancelada": GRIS}
ETIQUETA_ESTADO = {"asistio": "Asistió", "programada": "Programada", "inasistio": "Inasistió",
                   "reprogramada": "Reprogramada", "cancelada": "Cancelada"}

CSS = f"""
<style>
.block-container {{ padding-top: 2.2rem; max-width: 1280px; }}
h1, h2, h3 {{ color: {AZUL_OSCURO}; letter-spacing: -0.01em; }}
h1 {{ font-weight: 800; }}
/* barra lateral */
[data-testid="stSidebar"] h1, [data-testid="stSidebar"] h2, [data-testid="stSidebar"] h3 {{ color: #FFFFFF; }}
[data-testid="stSidebar"] img {{ border-radius: 14px; background: #FFFFFF; padding: 4px; }}
[data-testid="stSidebar"] [role="radiogroup"] label {{ padding: 6px 10px; border-radius: 10px; width: 100%; }}
[data-testid="stSidebar"] [role="radiogroup"] label:hover {{ background: rgba(255,255,255,.10); }}
[data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked) {{ background: {ROJO}; font-weight: 700; }}
/* botones y tarjetas nativas */
.stButton > button, .stDownloadButton > button, [data-testid="stFormSubmitButton"] > button {{
  border-radius: 10px; font-weight: 600; }}
[data-testid="stMetric"] {{ background: #FFFFFF; border-radius: 14px; }}
[data-testid="stDataFrame"] {{ border-radius: 12px; overflow: hidden; }}
[data-testid="stExpander"] {{ background: #FFFFFF; border-radius: 12px; }}
/* tarjetas propias */
.banner {{ background: linear-gradient(120deg, {AZUL_OSCURO} 0%, {AZUL} 70%, #3B63E8 100%); color: #fff;
  border-radius: 18px; padding: 26px 30px; margin-bottom: 18px; border-bottom: 5px solid {ROJO}; }}
.banner h1 {{ color: #fff; margin: 0 0 4px 0; font-size: 2rem; }}
.banner p {{ margin: 0; opacity: .9; }}
.kpi {{ background: #fff; border-radius: 16px; padding: 16px 18px; border-left: 6px solid var(--c);
  box-shadow: 0 2px 10px rgba(11,31,77,.08); height: 100%; }}
.kpi .t {{ font-size: .78rem; text-transform: uppercase; letter-spacing: .05em; color: #5B6785; font-weight: 700; }}
.kpi .v {{ font-size: 2.1rem; font-weight: 800; color: var(--c); line-height: 1.15; }}
.kpi .d {{ font-size: .82rem; color: #5B6785; }}
.seccion {{ font-weight: 800; color: {AZUL_OSCURO}; font-size: 1.1rem; margin: 18px 0 6px 0;
  padding-left: 10px; border-left: 5px solid {ROJO}; }}
</style>
"""


ROLES = {"medico": "Médico", "enfermeria": "Enfermería", "administrativo": "Administrativo",
         "administrador": "Administrador"}


def rol_txt(rol):
    return ROLES.get(rol, str(rol).capitalize())


def aplicar():
    """Inyecta los estilos. Se llama una vez por ejecución, antes de dibujar la pantalla."""
    st.markdown(CSS, unsafe_allow_html=True)


def logo_barra_lateral():
    if LOGO.exists():
        st.image(str(LOGO), width="stretch")


def logo_login():
    if LOGO.exists():
        _, c, _ = st.columns([1, 1, 1])
        c.image(str(LOGO), width="stretch")


def encabezado(titulo, subtitulo=""):
    st.markdown(f'<div class="banner"><h1>{titulo}</h1><p>{subtitulo}</p></div>', unsafe_allow_html=True)


def seccion(texto):
    st.markdown(f'<div class="seccion">{texto}</div>', unsafe_allow_html=True)


def kpi(columna, titulo, valor, detalle="", color=AZUL):
    columna.markdown(f'<div class="kpi" style="--c:{color}"><div class="t">{titulo}</div>'
                     f'<div class="v">{valor}</div><div class="d">{detalle}</div></div>', unsafe_allow_html=True)


def pintar_estados(df, columna="Estado"):
    """Devuelve la tabla con la columna de estado coloreada (verde asistió, rojo inasistió...)."""
    if df.empty or columna not in df:
        return df
    por_etiqueta = {ETIQUETA_ESTADO[k].lower(): v for k, v in COLOR_ESTADO.items()}

    def estilo(valor):
        color = por_etiqueta.get(str(valor).lower())
        return f"background-color: {color}22; color: {color}; font-weight: 700" if color else ""
    return df.style.map(estilo, subset=[columna])
