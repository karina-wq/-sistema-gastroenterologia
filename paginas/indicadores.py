"""Indicadores y reportes: los 6 indicadores de la tesis agrupados en sus 3 dimensiones
(Seguimiento de control, Calidad del control y Seguridad), con detalle y descarga a Excel."""
import os
import tempfile
from datetime import date

import pandas as pd
import streamlit as st

from sistema import reportes, seguridad
from sistema.base import hoy
from . import utilidades as u

# código del indicador → (dimensión, nombre, fórmula, ¿un valor más alto es mejor?)
INDICADORES = {
    "SEGUI_CUMPLIMIENTO": ("Seguimiento", "Cumplimiento de controles",
                           "Controles asistidos ÷ controles programados", True),
    "SEGUI_ACTUALIZADO": ("Seguimiento", "Seguimiento actualizado",
                          "Pacientes activos con control dentro del plazo ÷ pacientes activos", True),
    "CALID_PROTOCOLOS": ("Calidad", "Cumplimiento del protocolo",
                         "Atenciones con todos los pasos del protocolo ÷ atenciones", True),
    "CALID_COMPLETOS": ("Calidad", "Registros completos",
                        "Registros con todos los campos obligatorios ÷ registros", True),
    "SEGUR_EVENTOS": ("Seguridad", "Eventos adversos",
                      "Atenciones con evento adverso ÷ atenciones", False),
    "SEGUR_ACCESOS": ("Seguridad", "Accesos no autorizados",
                      "Intentos de acceso no exitosos ÷ intentos de acceso totales", False),
}
PREFIJO = {"Seguimiento": "SEGUI_", "Calidad": "CALID_", "Seguridad": "SEGUR_"}


def mostrar(usuario):
    st.title("Indicadores y reportes")

    c1, c2, c3 = st.columns([1, 1, 1])
    desde = c1.date_input("Desde", date(hoy().year, 1, 1), key="ind_desde", format="DD/MM/YYYY")
    hasta = c2.date_input("Hasta", hoy(), key="ind_hasta", format="DD/MM/YYYY")
    c3.write("")
    calcular_ahora = c3.button("Calcular", type="primary", key="ind_calcular")
    if desde > hasta:
        st.warning("La fecha «Desde» no puede ser posterior a «Hasta».")
        return

    # Los datos se calculan al pulsar «Calcular» y se guardan para no repetir las consultas en cada clic
    if calcular_ahora or "ind_datos" not in st.session_state:
        with st.spinner("Calculando indicadores…"):
            datos = calcular(usuario, desde, hasta)
        if datos is None:
            return
        st.session_state["ind_datos"] = datos
        st.session_state.pop("ind_excel", None)
    datos = st.session_state["ind_datos"]
    st.caption(f"Periodo calculado: {u.fecha_txt(datos['desde'])} al {u.fecha_txt(datos['hasta'])}")

    tabs = st.tabs(["Seguimiento de control", "Calidad del control", "Seguridad"])
    with tabs[0]:
        tarjetas(datos["indicadores"], "Seguimiento")
        grafico_mensual(datos["mensual"], "Seguimiento", datos)
        st.markdown("**Citas por estado**")
        if datos["citas"].empty:
            st.caption("Sin citas en el periodo.")
        else:
            citas = u.a_df(datos["citas"].to_dict("records"))
            st.bar_chart(citas.set_index("estado")["citas"], horizontal=True)
    with tabs[1]:
        tarjetas(datos["indicadores"], "Calidad")
        grafico_mensual(datos["mensual"], "Calidad", datos)
        t = datos["tiempos"]
        if not t.empty:
            st.markdown("**Tiempos de atención**")
            m = st.columns(4)
            m[0].metric("Atenciones", int(t["atenciones"].iloc[0]), border=True)
            m[1].metric("Espera promedio", minutos(t["espera_promedio_min"].iloc[0]), border=True)
            m[2].metric("Espera mediana", minutos(t["espera_mediana_min"].iloc[0]), border=True)
            m[3].metric("Duración promedio", minutos(t["duracion_promedio_min"].iloc[0]), border=True)
        s = datos["satisfaccion"]
        if not s.empty:
            st.markdown("**Satisfacción**")
            m = st.columns(3)
            m[0].metric("Encuestas", int(s["encuestas"].iloc[0]), border=True)
            puntaje = s["puntaje_promedio"].iloc[0]
            m[1].metric("Puntaje promedio (1 a 5)", "—" if pd.isna(puntaje) else f"{puntaje:.2f}", border=True)
            espera = s["pct_espera_aceptable"].iloc[0]
            m[2].metric("Espera aceptable", "—" if pd.isna(espera) else f"{espera:.1f} %", border=True)
        st.markdown("**Registros incompletos (para corregir)**")
        tabla(datos["incompletos"], "registros_incompletos.csv",
              {"atencion_id": "N.º atención", "fecha_atencion": "Fecha", "paciente": "Paciente",
               "medico": "Médico", "campos_faltantes": "Campos faltantes"})
    with tabs[2]:
        tarjetas(datos["indicadores"], "Seguridad")
        grafico_mensual(datos["mensual"], "Seguridad", datos)
        st.markdown("**Eventos adversos del periodo**")
        tabla(datos["eventos"], "eventos_adversos.csv",
              {"fecha_evento": "Fecha", "paciente": "Paciente", "tipo": "Tipo", "gravedad": "Gravedad",
               "descripcion": "Descripción", "accion_tomada": "Acción tomada", "procedimiento": "Procedimiento"},
              columnas=["fecha_evento", "paciente", "tipo", "gravedad", "descripcion", "accion_tomada", "procedimiento"])
        if u.tiene(usuario, "auditoria.ver"):
            st.markdown("**Accesos no exitosos del periodo**")
            ok, accesos = u.ejecutar(seguridad.consultar_accesos, usuario, datos["desde"], datos["hasta"], True, 200)
            if ok:
                tabla(pd.DataFrame(accesos), "accesos_no_exitosos.csv",
                      {"created_at": "Fecha y hora", "email_intentado": "Correo", "resultado": "Resultado",
                       "motivo": "Motivo", "ip": "IP"},
                      columnas=["created_at", "email_intentado", "resultado", "motivo", "ip"])

    st.divider()
    st.markdown("##### Reporte completo en Excel")
    st.caption("Incluye todas las tablas del periodo en hojas separadas. La descarga queda registrada en la bitácora.")
    if st.button("Preparar archivo Excel", key="ind_preparar"):
        with st.spinner("Generando el archivo…"):
            contenido = exportar(usuario, datos["desde"], datos["hasta"])
        if contenido:
            st.session_state["ind_excel"] = (contenido, f"reporte_indicadores_{datos['desde']}_{datos['hasta']}.xlsx")
    if "ind_excel" in st.session_state:
        contenido, nombre = st.session_state["ind_excel"]
        st.download_button("⬇ Descargar Excel", contenido, nombre,
                           "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", key="ind_descargar")


# ----------------------------------------------------------------------
def calcular(usuario, desde, hasta):
    """Pide al paquete todos los datos del periodo. Devuelve None si algo falla."""
    consultas = {
        "indicadores": (reportes.indicadores, usuario, desde, hasta),
        "mensual": (reportes.indicadores_mensuales, usuario),
        "tiempos": (reportes.tiempos_atencion, usuario, desde, hasta),
        "satisfaccion": (reportes.satisfaccion, usuario, desde, hasta),
        "citas": (reportes.citas_por_estado, usuario, desde, hasta),
        "incompletos": (reportes.registros_incompletos, usuario, desde, hasta),
        "eventos": (reportes.eventos_adversos_detalle, usuario, desde, hasta),
    }
    datos = {"desde": desde, "hasta": hasta}
    for nombre, (funcion, *args) in consultas.items():
        ok, valor = u.ejecutar(funcion, *args)
        if not ok:
            return None
        datos[nombre] = valor
    return datos


def col_codigo(df):
    """Nombre de la columna que contiene los códigos de indicador (SEGUI_..., CALID_..., SEGUR_...)."""
    for c in df.columns:
        if df[c].astype(str).isin(list(INDICADORES)).any():
            return c
    return None


def tarjetas(ind, dimension):
    """Dibuja las dos tarjetas de la dimensión."""
    codigos = [c for c, v in INDICADORES.items() if v[0] == dimension]
    col = col_codigo(ind) if not ind.empty else None
    for caja, codigo in zip(st.columns(len(codigos)), codigos):
        _, nombre, formula, mayor = INDICADORES[codigo]
        fila = ind[ind[col].astype(str) == codigo] if col else ind.iloc[0:0]
        if fila.empty:
            caja.metric(nombre, "—", border=True)
            caja.caption(f"{formula}. Sin datos en el periodo.")
            continue
        r = fila.iloc[0]
        pct = r["porcentaje"]
        caja.metric(nombre, "—" if pd.isna(pct) else f"{float(pct):.1f} %", border=True)
        detalle = ""
        if not pd.isna(r.get("numerador")) and not pd.isna(r.get("denominador")):
            detalle = f" {int(r['numerador'])} de {int(r['denominador'])}."
        caja.caption(f"{formula}.{detalle} {'Más alto es mejor.' if mayor else 'Más bajo es mejor.'}")


def grafico_mensual(mens, dimension, datos):
    """Evolución mensual (%) de los indicadores de la dimensión, dentro del periodo calculado."""
    col = col_codigo(mens) if not mens.empty else None
    if not col:
        return
    sub = mens[mens[col].astype(str).str.startswith(PREFIJO[dimension])].copy()
    sub["mes"] = pd.to_datetime(sub["mes"])
    sub = sub[(sub["mes"] >= pd.Timestamp(datos["desde"].replace(day=1))) & (sub["mes"] <= pd.Timestamp(datos["hasta"]))]
    if sub.empty:
        st.caption("Sin evolución mensual disponible para este periodo.")
        return
    sub["Indicador"] = sub[col].map(lambda c: INDICADORES[c][1] if c in INDICADORES else c)
    tabla_mensual = sub.pivot_table(index="mes", columns="Indicador", values="porcentaje", aggfunc="first")
    st.markdown("**Evolución mensual (%)**")
    st.line_chart(tabla_mensual)


def tabla(df, archivo_csv, nombres, columnas=None):
    """Tabla con botón de descarga CSV; avisa si no hay filas."""
    if df is None or df.empty:
        st.caption("Sin registros en el periodo.")
        return
    vista = u.a_df(df.to_dict("records"), columnas or list(nombres), nombres)
    st.dataframe(vista, hide_index=True, width="stretch")
    st.download_button("Descargar (CSV)", u.csv_bytes(vista), archivo_csv, "text/csv", key=f"csv_{archivo_csv}")


def minutos(valor):
    return "—" if pd.isna(valor) else f"{float(valor):.1f} min"


def exportar(usuario, desde, hasta):
    """Genera el Excel con el paquete (reportes.exportar_excel) y devuelve su contenido."""
    with tempfile.TemporaryDirectory() as carpeta:
        ruta = os.path.join(carpeta, "reporte_indicadores.xlsx")
        ok, _ = u.ejecutar(reportes.exportar_excel, usuario, desde, hasta, ruta)
        if not ok:
            return None
        with open(ruta, "rb") as f:
            return f.read()
