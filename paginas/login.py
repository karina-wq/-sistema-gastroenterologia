"""Pantalla de inicio de sesión."""
import time

import streamlit as st

from sistema import seguridad
from . import utilidades as u


def mostrar():
    _, centro, _ = st.columns([1, 1.3, 1])
    with centro:
        st.title("🏥 Control de Pacientes")
        st.caption("Servicio de Gastroenterología · Hospital Nacional Arzobispo Loayza")
        u.mostrar_avisos()
        # st.form agrupa los campos: la app no hace nada hasta que se pulsa "Ingresar"
        with st.form("form_login"):
            correo = st.text_input("Correo")
            clave = st.text_input("Contraseña", type="password")
            entrar = st.form_submit_button("Ingresar", type="primary", width="stretch")
        if entrar:
            ip, agente = u.ip_y_agente()
            ok, resultado = u.ejecutar(seguridad.autenticar, correo, clave, ip, agente)
            if ok and resultado["ok"]:
                st.session_state["usuario"] = resultado["usuario"]
                st.session_state["_ultima_actividad"] = time.time()
                st.rerun()
            elif ok:
                st.error(resultado["mensaje"])   # clave incorrecta, cuenta bloqueada, etc.
        st.caption("Si olvidó su contraseña o su cuenta está bloqueada, comuníquese con el administrador.")
