"""Alertas de seguimiento: controles vencidos y pacientes inasistentes."""
import streamlit as st

from sistema import clinico
from . import utilidades as u


def mostrar(usuario):
    st.title("Alertas de seguimiento")
    st.caption("Pacientes en control que necesitan atención del servicio para no abandonar su seguimiento.")

    seccion = st.radio("Ver", ["Controles vencidos", "Inasistentes recientes"], horizontal=True,
                       label_visibility="collapsed", key="alertas_seccion")

    if seccion == "Controles vencidos":
        ok, filas = u.ejecutar(clinico.alertas_seguimiento, usuario)
        if not ok:
            return
        st.metric("Casos con control vencido", len(filas), border=True)
        if not filas:
            st.success("No hay controles vencidos.")
            return
        df = u.a_df(filas)
        st.dataframe(df, hide_index=True, width="stretch")
        st.download_button("Descargar lista (CSV)", u.csv_bytes(df), "controles_vencidos.csv", "text/csv")
    else:
        dias = st.slider("Mirar los últimos (días)", 7, 180, 60, step=1, key="alertas_dias")
        ok, filas = u.ejecutar(clinico.pacientes_inasistentes, usuario, dias)
        if not ok:
            return
        st.metric("Pacientes con inasistencias", len(filas), border=True)
        if not filas:
            st.success("Ningún paciente con caso activo faltó a sus citas en ese periodo.")
            return
        df = u.a_df(filas, ["codigo", "paciente", "telefono", "inasistencias", "ultima_inasistencia"],
                    {"codigo": "Código", "paciente": "Paciente", "telefono": "Teléfono",
                     "inasistencias": "Inasistencias", "ultima_inasistencia": "Última inasistencia"})
        st.dataframe(df, hide_index=True, width="stretch")
        st.download_button("Descargar lista (CSV)", u.csv_bytes(df), "pacientes_inasistentes.csv", "text/csv")
