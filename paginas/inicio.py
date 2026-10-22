"""Pantalla de inicio: resumen del día según los permisos del usuario."""
import streamlit as st

from sistema import clinico
from sistema.base import hoy
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
    st.title(f"Bienvenido/a, {usuario['nombres']}")
    st.caption(f"Rol: **{usuario['rol']}** · Hoy es {u.fecha_txt(hoy())}")

    metricas = []
    if u.tiene(usuario, "citas.gestionar"):
        ok, citas = u.ejecutar(clinico.listar_citas, usuario, hoy(), hoy())
        if ok:
            vigentes = [c for c in citas if c["estado"] in ("programada", "asistio")]
            metricas.append(("Citas de hoy", len(vigentes), f"{sum(c['estado'] == 'asistio' for c in vigentes)} ya asistieron"))
        ok, pendientes = u.ejecutar(clinico.recordatorios_pendientes, usuario)
        if ok:
            metricas.append(("Recordatorios por enviar", len(pendientes), "cuya hora de envío ya llegó"))
    if u.tiene(usuario, "pacientes.ver"):
        ok, vencidos = u.ejecutar(clinico.alertas_seguimiento, usuario)
        if ok:
            metricas.append(("Controles vencidos", len(vencidos), "pacientes que superaron su plazo de control"))

    if metricas:
        columnas = st.columns(len(metricas))
        for col, (titulo, valor, ayuda) in zip(columnas, metricas):
            col.metric(titulo, valor, border=True)
            col.caption(ayuda)

    st.subheader("Lo que puede hacer con su rol")
    for permiso in sorted(usuario["permisos"]):
        st.markdown(f"- {FUNCIONES.get(permiso, permiso)}")
    st.caption("Use el menú de la izquierda para ir a cada pantalla.")
