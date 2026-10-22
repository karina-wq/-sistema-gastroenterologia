"""Agenda de citas y recordatorios."""
import smtplib
from datetime import date, time, timedelta

import streamlit as st

from sistema import clinico
from sistema.base import hoy
from . import correo
from . import estilo
from . import utilidades as u

ESTADOS = ["Todos", "programada", "asistio", "inasistio", "reprogramada", "cancelada"]
ETIQUETA = {"programada": "Programada", "asistio": "Asistió", "inasistio": "No asistió",
            "reprogramada": "Reprogramada", "cancelada": "Cancelada"}
MAX_ENVIO_MASIVO = 50


def mostrar(usuario):
    st.title("Agenda y recordatorios")
    seccion = st.radio("Sección", ["Citas", "Recordatorios"], horizontal=True,
                       label_visibility="collapsed", key="ag_seccion")
    if seccion == "Citas":
        citas(usuario)
    else:
        recordatorios(usuario)


# ----------------------------------------------------------------------
# Citas
# ----------------------------------------------------------------------
def citas(usuario):
    medicos = u.medicos_activos()
    c1, c2, c3, c4 = st.columns(4)
    desde = c1.date_input("Desde", hoy(), key="ag_desde", format="DD/MM/YYYY")
    hasta = c2.date_input("Hasta", hoy() + timedelta(days=7), key="ag_hasta", format="DD/MM/YYYY")
    estado = c3.selectbox("Estado", ESTADOS, format_func=lambda e: ETIQUETA.get(e, e), key="ag_estado")
    medico = c4.selectbox("Médico", [None] + list(medicos), key="ag_medico",
                          format_func=lambda i: "Todos" if i is None else medicos[i])
    if desde > hasta:
        st.warning("La fecha «Desde» no puede ser posterior a «Hasta».")
        return

    ok, filas = u.ejecutar(clinico.listar_citas, usuario, desde, hasta,
                           None if estado == "Todos" else estado, medico)
    if not ok:
        return
    if not filas:
        st.info("No hay citas en ese rango.")
        return

    df = u.a_df(filas, ["fecha_programada", "hora_programada", "codigo", "paciente", "telefono", "medico", "estado"],
                {"fecha_programada": "Fecha", "hora_programada": "Hora", "codigo": "Código", "paciente": "Paciente",
                 "telefono": "Teléfono", "medico": "Médico", "estado": "Estado"})
    df["Estado"] = df["Estado"].map(lambda e: ETIQUETA.get(e, e))
    st.dataframe(estilo.pintar_estados(df), hide_index=True, width="stretch")
    st.caption(f"{len(filas)} citas.")

    st.markdown("##### Acciones sobre una cita")
    por_id = {c["id"]: c for c in filas}
    elegida = st.selectbox(
        "Elija una cita", list(por_id), index=None, placeholder="Elija una cita de la lista", key="ag_cita",
        format_func=lambda i: f"{u.fecha_txt(por_id[i]['fecha_programada'])} {u.hora_txt(por_id[i]['hora_programada'])}"
                              f" · {por_id[i]['paciente']} · {ETIQUETA.get(por_id[i]['estado'])}")
    if elegida:
        acciones(usuario, por_id[elegida])


def acciones(usuario, c):
    cid = c["id"]
    estado = c["estado"]
    if estado in ("programada", "inasistio"):
        a, b = st.columns(2)
        if a.button("✅ Registrar asistencia", key=f"asis_{cid}", type="primary"):
            ok, _ = u.ejecutar(clinico.registrar_asistencia, usuario, cid)
            if ok:
                u.avisar("Asistencia registrada. Ya puede iniciar la atención clínica.")
                st.rerun()
        if estado == "programada" and b.button("🚫 Marcar inasistencia", key=f"inas_{cid}"):
            ok, _ = u.ejecutar(clinico.marcar_inasistencia, usuario, cid)
            if ok:
                u.avisar("Inasistencia registrada.", "warning")
                st.rerun()

    if estado == "programada":
        with st.expander("Reprogramar"):
            with st.form(f"form_repro_{cid}"):
                f1, f2, f3 = st.columns(3)
                fecha = f1.date_input("Nueva fecha", hoy(), min_value=hoy(), format="DD/MM/YYYY")
                hora = f2.time_input("Hora", time(9, 0), step=900)
                canal = f3.radio("Recordatorio por", ["correo", "whatsapp", "sms"], horizontal=True)
                guardar = st.form_submit_button("Reprogramar", type="primary")
            if guardar:
                ok, _ = u.ejecutar(clinico.reprogramar_cita, usuario, cid, fecha, hora, canal)
                if ok:
                    u.avisar("Cita reprogramada: la original quedó como «Reprogramada» y se creó la nueva.")
                    st.rerun()
        with st.expander("Cancelar cita"):
            with st.form(f"form_cancel_{cid}"):
                motivo = st.text_input("Motivo de la cancelación (opcional)")
                guardar = st.form_submit_button("Cancelar la cita")
            if guardar:
                ok, _ = u.ejecutar(clinico.cancelar_cita, usuario, cid, motivo)
                if ok:
                    u.avisar("Cita cancelada.", "warning")
                    st.rerun()

    if estado == "asistio" and u.tiene(usuario, "atenciones.ver"):
        if st.button("🩺 Ir a la atención clínica de esta cita", key=f"ir_at_{cid}", type="primary"):
            u.ir_a_pagina("Atención clínica", fecha=c["fecha_programada"], cita=cid)

    if estado in ("reprogramada", "cancelada"):
        st.caption("Esta cita ya no admite acciones.")


# ----------------------------------------------------------------------
# Recordatorios
# ----------------------------------------------------------------------
def enviar_uno(usuario, r):
    """Envía el recordatorio por correo y lo marca. Devuelve 'enviado', 'fallido' o 'config'.
    'config' = problema de conexión o de la cuenta de Gmail: el recordatorio NO se marca
    (sigue pendiente) para poder reintentar cuando se corrija la configuración."""
    try:
        correo.enviar(r["email"], clinico.mensaje_recordatorio(r))
    except smtplib.SMTPRecipientsRefused:   # el correo del paciente no existe o fue rechazado
        u.ejecutar(clinico.marcar_recordatorio, usuario, r["id"], False)
        return "fallido"
    except Exception as e:
        st.session_state["_ultimo_error_correo"] = type(e).__name__
        return "config"
    ok, _ = u.ejecutar(clinico.marcar_recordatorio, usuario, r["id"], True)
    return "enviado" if ok else "config"


def recordatorios(usuario):
    ok, pendientes = u.ejecutar(clinico.recordatorios_pendientes, usuario)
    if not ok:
        return
    st.metric("Recordatorios por enviar", len(pendientes), border=True)
    st.caption("Son los recordatorios cuya hora de envío ya llegó (2 días antes de la cita, 9:00 a. m.).")

    puede_correo = correo.configurado()
    if not puede_correo:
        st.info("El envío por correo aún no está configurado. Mientras tanto, copie el mensaje y márquelo "
                "como enviado. Para activarlo agregue GMAIL_USER y GMAIL_APP_PASSWORD en los Secretos (ver la guía).")
    if not pendientes:
        st.success("No hay recordatorios pendientes.")
        return

    con_correo = [r for r in pendientes if r["email"]]
    if puede_correo and con_correo:
        with st.expander(f"Enviar por correo todos los que tienen correo ({len(con_correo)})"):
            lote = con_correo[:MAX_ENVIO_MASIVO]
            st.caption(f"Se envían como máximo {MAX_ENVIO_MASIVO} por vez ({len(lote)} ahora).")
            if st.button(f"Enviar {len(lote)} recordatorios", key="rec_masivo", type="primary"):
                barra = st.progress(0.0)
                conteo = {"enviado": 0, "fallido": 0, "config": 0}
                for i, r in enumerate(lote, 1):
                    resultado = enviar_uno(usuario, r)
                    conteo[resultado] += 1
                    barra.progress(i / len(lote))
                    if resultado == "config":   # no seguir insistiendo si Gmail rechaza la cuenta
                        break
                u.avisar(f"Enviados: {conteo['enviado']} · Rechazados por el destinatario: {conteo['fallido']}",
                         "success" if not conteo["config"] else "warning")
                if conteo["config"]:
                    u.avisar("Se detuvo el envío: no se pudo conectar con Gmail o la cuenta fue rechazada "
                             f"({st.session_state.get('_ultimo_error_correo', 'error')}). "
                             "Revise GMAIL_USER y GMAIL_APP_PASSWORD.", "error")
                st.rerun()

    st.markdown("##### Detalle")
    for r in pendientes[:30]:
        titulo = (f"{r['paciente']} · cita del {u.fecha_txt(r['fecha_programada'])} {u.hora_txt(r['hora_programada'])}"
                  f" · {r['canal']}")
        with st.expander(titulo):
            st.text_area("Mensaje", clinico.mensaje_recordatorio(r), height=110, key=f"rec_msg_{r['id']}")
            st.caption(f"Teléfono: {r['telefono'] or '—'} · Correo: {r['email'] or '—'}")
            a, b, c = st.columns(3)
            if puede_correo and r["email"] and a.button("📧 Enviar por correo", key=f"rec_env_{r['id']}"):
                resultado = enviar_uno(usuario, r)
                if resultado == "enviado":
                    u.avisar("Correo enviado y recordatorio marcado como enviado.")
                elif resultado == "fallido":
                    u.avisar("El destinatario rechazó el correo; se marcó como fallido.", "warning")
                else:
                    u.avisar("No se pudo enviar: revise la configuración de Gmail "
                             f"({st.session_state.get('_ultimo_error_correo', 'error')}).", "error")
                st.rerun()
            if b.button("Marcar como enviado", key=f"rec_ok_{r['id']}"):
                ok, _ = u.ejecutar(clinico.marcar_recordatorio, usuario, r["id"], True)
                if ok:
                    st.rerun()
            if c.button("Marcar como fallido", key=f"rec_no_{r['id']}"):
                ok, _ = u.ejecutar(clinico.marcar_recordatorio, usuario, r["id"], False)
                if ok:
                    st.rerun()
    if len(pendientes) > 30:
        st.caption(f"Se muestran los primeros 30 de {len(pendientes)}.")
