"""Pantalla de inicio: resumen del día según los permisos del usuario."""
from datetime import date, timedelta

import pandas as pd
import streamlit as st

from sistema import clinico, reportes
from sistema.base import hoy
from . import estilo, indicadores
from . import utilidades as u

# Qué puede hacer cada permiso, en palabras simples (se muestra según el rol)
FUNCIONES = {
    "pacientes.ver": "Buscar pacientes y ver sus fichas y alertas de seguimiento",
    "pacientes.editar": "Registrar pacientes y abrir sus casos de control",
    "citas.gestionar": "Programar, reprogramar y cancelar citas; registrar asistencia; enviar recordatorios",
    "atenciones.ver": "Consultar atenciones clínicas e historiales",
    "atenciones.registrar": "Registrar atenciones con la lista de verificación del protocolo",
    "eventos.registrar": "Registrar eventos adversos",
    "reportes.ver": "Ver indicadores y descargar reportes en Excel",
    "auditoria.ver": "Consultar la bitácora de auditoría y los accesos al sistema",
    "usuarios.administrar": "Crear y administrar usuarios",
}


def mostrar(usuario):
    estilo.encabezado(f"Bienvenido/a, {usuario['nombres']}",
                      f"{estilo.rol_txt(usuario['rol'])} · Hoy es {u.fecha_txt(hoy())} · Servicio de Gastroenterología")

    # --- Tarjetas del día ---
    tarjetas = []
    citas_14d = []
    if u.tiene(usuario, "citas.gestionar"):
        ok, citas_14d = u.ejecutar(clinico.listar_citas, usuario, hoy() - timedelta(days=13), hoy())
        if ok:
            de_hoy = [c for c in citas_14d if c["fecha_programada"] == hoy() and c["estado"] in ("programada", "asistio")]
            asistieron = sum(c["estado"] == "asistio" for c in de_hoy)
            tarjetas.append(("Citas de hoy", len(de_hoy), f"{asistieron} ya asistieron", estilo.AZUL))
        else:
            citas_14d = []
        ok, pendientes = u.ejecutar(clinico.recordatorios_pendientes, usuario)
        if ok:
            tarjetas.append(("Recordatorios por enviar", len(pendientes), "cuya hora de envío ya llegó", estilo.AMBAR))
    vencidos = []
    if u.tiene(usuario, "pacientes.ver"):
        ok, vencidos = u.ejecutar(clinico.alertas_seguimiento, usuario)
        if ok:
            tarjetas.append(("Controles vencidos", len(vencidos), "pacientes que superaron su plazo", estilo.ROJO))
        else:
            vencidos = []
    if tarjetas:
        for col, (titulo, valor, detalle, color) in zip(st.columns(len(tarjetas)), tarjetas):
            estilo.kpi(col, titulo, valor, detalle, color)

    # --- Accesos rápidos ---
    accesos = []
    if u.tiene(usuario, "pacientes.editar"):
        accesos.append(("➕ Registrar paciente", "Pacientes", {"pac_seccion": "Registrar paciente nuevo"}))
    if u.tiene(usuario, "citas.gestionar"):
        accesos.append(("📅 Ver agenda", "Agenda y recordatorios", {}))
    if u.tiene(usuario, "atenciones.ver"):
        accesos.append(("🩺 Atención clínica", "Atención clínica", {}))
    if u.tiene(usuario, "pacientes.ver"):
        accesos.append(("🔔 Alertas", "Alertas de seguimiento", {}))
    if accesos:
        estilo.seccion("Accesos rápidos")
        for col, (texto, pagina, destino) in zip(st.columns(len(accesos)), accesos):
            if col.button(texto, key=f"acc_{pagina}", width="stretch"):
                u.ir_a_pagina(pagina, **destino)

    # --- Gráfico de citas ---
    if citas_14d:
        estilo.seccion("Citas de los últimos 14 días, por estado")
        df = pd.DataFrame(citas_14d)
        df["fecha"] = pd.to_datetime(df["fecha_programada"]).dt.strftime("%d/%m")
        orden = [e for e in estilo.COLOR_ESTADO if e in set(df["estado"])]
        tabla = df.pivot_table(index="fecha", columns="estado", values="id", aggfunc="count", fill_value=0)
        fechas = [(hoy() - timedelta(days=i)).strftime("%d/%m") for i in range(13, -1, -1)]
        tabla = tabla.reindex(fechas, fill_value=0)[orden]
        tabla.columns = [estilo.ETIQUETA_ESTADO[e] for e in orden]
        st.bar_chart(tabla, color=[estilo.COLOR_ESTADO[e] for e in orden], stack=True, height=260)

    # --- Indicadores resumidos (solo roles con permiso de reportes) ---
    if u.tiene(usuario, "reportes.ver"):
        estilo.seccion(f"Indicadores del año {hoy().year}")
        ok, ind = u.ejecutar(reportes.indicadores, usuario, date(hoy().year, 1, 1), hoy())
        if ok:
            for dimension, titulo in (("Seguimiento", "Seguimiento de control"), ("Calidad", "Calidad del control"),
                                      ("Seguridad", "Seguridad")):
                st.caption(titulo)
                indicadores.tarjetas(ind, dimension)

    # --- Pacientes que requieren contacto ---
    if vencidos:
        estilo.seccion("Pacientes con control vencido (primeros 8)")
        st.dataframe(u.a_df(vencidos[:8]), hide_index=True, width="stretch")
        st.caption("La lista completa y su descarga están en «Alertas de seguimiento».")

    with st.expander("¿Qué puedo hacer con mi rol?"):
        for permiso in sorted(usuario["permisos"]):
            st.markdown(f"- {FUNCIONES.get(permiso, permiso)}")
