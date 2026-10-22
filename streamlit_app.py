# =====================================================================
# FASE 3 - INTERFAZ WEB (Streamlit)
# Sistema de control de pacientes - Gastroenterología
# Hospital Nacional Arzobispo Loayza, Lima - Perú, 2026
# =====================================================================
#
# QUÉ HACE ESTE ARCHIVO
#   Es la "puerta de entrada" de la aplicación: pide el inicio de sesión,
#   arma el menú según el rol del usuario y muestra la pantalla elegida.
#   TODA la lógica (permisos, validaciones, auditoría, indicadores) está en
#   el paquete `sistema/` de la Fase 2; las pantallas de la carpeta
#   `paginas/` solo muestran datos y llaman a esas funciones.
#
# CÓMO SE CONECTA A NEON
#   La cadena de conexión NO está en el código: se lee de los "Secretos" de
#   Streamlit (NEON_URL). Ver .streamlit/secrets.toml.example y la guía.
#
# CÓMO SE EJECUTA EN SU COMPUTADORA (prueba)
#   pip install -r requirements.txt
#   streamlit run streamlit_app.py

import streamlit as st

# Debe ser la PRIMERA orden de Streamlit del archivo
st.set_page_config(page_title="Control de Pacientes · Gastroenterología", page_icon="🏥",
                   layout="wide", initial_sidebar_state="expanded")

from paginas import administracion, agenda, alertas, atencion, cuenta, indicadores, inicio, login, pacientes
from paginas import utilidades as u

# --- 1. ¿Está configurada la conexión con la base de datos? -------------------
if not u.preparar_secretos():
    st.error("Falta configurar la conexión con la base de datos.")
    st.markdown("En Streamlit Cloud: **Settings → Secrets** y pegue la línea:  \n"
                "`NEON_URL = \"postgresql://usuario:clave@...neon.tech/neondb?sslmode=require\"`")
    st.stop()

# --- 2. ¿Hay una sesión iniciada? Si no, se muestra el inicio de sesión -------
usuario = st.session_state.get("usuario")
if usuario is None:
    login.mostrar()
    st.stop()

u.controlar_inactividad()   # cierra la sesión tras 30 minutos sin actividad

# --- 3. Menú según los permisos del rol ----------------------------------------
# nombre de la pantalla → (módulo, permisos que la habilitan: basta con tener uno)
PAGINAS = {
    "Inicio": (inicio, None),
    "Pacientes": (pacientes, ["pacientes.ver"]),
    "Agenda y recordatorios": (agenda, ["citas.gestionar"]),
    "Atención clínica": (atencion, ["atenciones.ver"]),
    "Alertas de seguimiento": (alertas, ["pacientes.ver"]),
    "Indicadores y reportes": (indicadores, ["reportes.ver"]),
    "Administración": (administracion, ["usuarios.administrar", "auditoria.ver"]),
    "Mi cuenta": (cuenta, None),
}
permitidas = [nombre for nombre, (_, permisos) in PAGINAS.items()
              if permisos is None or any(u.tiene(usuario, p) for p in permisos)]

# Si otra pantalla pidió ir a una pantalla concreta, se aplica antes de dibujar el menú
destino = st.session_state.pop("_ir_pagina", None)
if destino in permitidas:
    st.session_state["pagina"] = destino
if st.session_state.get("pagina") not in permitidas:
    st.session_state.pop("pagina", None)

with st.sidebar:
    st.markdown("### 🏥 Gastroenterología")
    st.caption("Hospital Nacional Arzobispo Loayza")
    st.markdown(f"**{usuario['nombre_completo']}**  \n{usuario['rol']}")
    pagina = st.radio("Menú", permitidas, key="pagina", label_visibility="collapsed")
    st.divider()
    if u.hay_datos_simulados():
        st.warning("La base tiene **datos simulados** de prueba. Deben eliminarse antes de las mediciones reales.")
    if st.button("Cerrar sesión", width="stretch"):
        u.cerrar_sesion()

# --- 4. Mostrar la pantalla elegida ---------------------------------------------
u.mostrar_avisos()
PAGINAS[pagina][0].mostrar(usuario)
