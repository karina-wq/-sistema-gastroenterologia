"""Pacientes: búsqueda, ficha, historial, registro, casos de control y programación de citas."""
from datetime import date, time

import streamlit as st

from sistema import clinico
from sistema.base import hoy
from . import utilidades as u

def edad_en_anios(nacimiento):
    h = hoy()
    return h.year - nacimiento.year - ((h.month, h.day) < (nacimiento.month, nacimiento.day))


NIVELES = ["", "Sin instrucción", "Primaria", "Secundaria", "Técnico", "Superior universitario", "Posgrado"]


def mostrar(usuario):
    st.title("Pacientes")

    secciones = ["Buscar paciente"]
    if u.tiene(usuario, "pacientes.editar"):
        secciones.append("Registrar paciente nuevo")

    # Si otra pantalla pidió abrir una sección concreta, se aplica antes de dibujar el selector
    destino = st.session_state.pop("_destino_pac_seccion", None)
    if destino in secciones:
        st.session_state["pac_seccion"] = destino
    seccion = st.radio("Sección", secciones, horizontal=True, label_visibility="collapsed", key="pac_seccion")

    if seccion == "Buscar paciente":
        buscar(usuario)
    else:
        registrar(usuario)


# ----------------------------------------------------------------------
# Buscar y ver ficha
# ----------------------------------------------------------------------
def buscar(usuario):
    with st.form("form_buscar"):
        consulta = st.text_input("Buscar por nombre, apellido, DNI o código (ej. P-00012)")
        enviar = st.form_submit_button("Buscar", type="primary")
    if enviar:
        ok, filas = u.ejecutar(clinico.buscar_pacientes, usuario, consulta)
        if ok:
            st.session_state["pac_busqueda"] = filas
            st.session_state.pop("pac_sel", None)

    filas = st.session_state.get("pac_busqueda")
    if filas is None:
        return
    if not filas:
        st.info("No se encontraron pacientes con ese dato.")
        return

    st.dataframe(u.a_df(filas, ["codigo", "dni", "apellidos", "nombres", "sexo", "edad", "telefono", "activo"],
                        {"codigo": "Código", "dni": "DNI", "apellidos": "Apellidos", "nombres": "Nombres",
                         "sexo": "Sexo", "edad": "Edad", "telefono": "Teléfono", "activo": "Activo"}),
                 hide_index=True, width="stretch")

    etiquetas = {f["id"]: f"{f['codigo']} · {f['apellidos']}, {f['nombres']}" for f in filas}
    preseleccion = st.session_state.pop("_destino_pac_sel", None)
    if preseleccion in etiquetas:
        st.session_state["pac_sel"] = preseleccion
    elegido = st.selectbox("Ver la ficha de:", list(etiquetas), format_func=etiquetas.get, index=None,
                           placeholder="Elija un paciente de la lista", key="pac_sel")
    if elegido:
        st.divider()
        ficha(usuario, elegido)


def ficha(usuario, pid):
    p = u.leer_cache(f"ficha_{pid}", clinico.obtener_paciente, usuario, pid)   # deja constancia "VER" una sola vez
    if p is None:
        return

    st.subheader(f"{p['nombres']} {p['apellidos']}  ·  {p['codigo']}")
    edad = edad_en_anios(p["fecha_nacimiento"])
    c1, c2, c3 = st.columns(3)
    c1.markdown(f"**DNI:** {p['dni'] or '—'}  \n**Sexo:** {p['sexo']}  \n**Edad:** {edad} años")
    c2.markdown(f"**Teléfono:** {p['telefono'] or '—'}  \n**Correo:** {p['email'] or '—'}  \n"
                f"**Dirección:** {p['direccion'] or '—'}")
    c3.markdown(f"**Nivel educativo:** {p['nivel_educativo'] or '—'}  \n"
                f"**Contacto de emergencia:** {p['contacto_emergencia'] or '—'}")

    # --- Casos en control ---
    st.markdown("##### Casos en control")
    casos = p["casos"]
    caso_activo = next((c for c in casos if c["estado"] == "en_seguimiento"), None)
    if casos:
        st.dataframe(u.a_df(casos, ["diagnostico_cie10", "diagnostico", "estado", "fecha_ingreso", "fecha_cierre",
                                    "frecuencia_control_dias", "plazo_actualizacion_dias", "fecha_ultimo_control"],
                            {"diagnostico_cie10": "CIE-10", "diagnostico": "Diagnóstico", "estado": "Estado",
                             "fecha_ingreso": "Ingreso", "fecha_cierre": "Cierre",
                             "frecuencia_control_dias": "Control cada (días)",
                             "plazo_actualizacion_dias": "Plazo (días)", "fecha_ultimo_control": "Último control"}),
                     hide_index=True, width="stretch")
    else:
        st.info("Este paciente aún no tiene un caso en el programa de control.")

    # --- Acciones ---
    if u.tiene(usuario, "pacientes.editar"):
        with st.expander("Editar datos del paciente"):
            editar(usuario, p)
        if caso_activo is None:
            with st.expander("Abrir caso de control", expanded=not casos):
                abrir_caso(usuario, p)
    if caso_activo and u.tiene(usuario, "citas.gestionar"):
        with st.expander("Programar próxima cita"):
            programar_cita(usuario, p, caso_activo)
    if caso_activo and u.tiene(usuario, "atenciones.registrar"):
        with st.expander("Cerrar el caso (alta o abandono)"):
            cerrar_caso(usuario, p, caso_activo)

    # --- Historial ---
    if u.tiene(usuario, "atenciones.ver"):
        st.markdown("##### Historial de atenciones")
        h = u.leer_cache(f"hist_{pid}", clinico.historial_paciente, usuario, pid)
        if h is None:
            return
        if not h:
            st.caption("Sin atenciones registradas.")
            return
        df = u.a_df(h, ["id", "fecha_atencion", "estado", "registro_completo", "diagnostico", "motivo_consulta",
                        "tratamiento", "medico", "procedimientos", "eventos_adversos"],
                    {"id": "N.º", "fecha_atencion": "Fecha", "estado": "Estado", "registro_completo": "Completo",
                     "diagnostico": "Diagnóstico", "motivo_consulta": "Motivo", "tratamiento": "Tratamiento",
                     "medico": "Médico", "procedimientos": "Procedimientos", "eventos_adversos": "Eventos adversos"})
        df["Procedimientos"] = df["Procedimientos"].map(lambda v: ", ".join(v) if isinstance(v, list) else v)
        st.dataframe(df, hide_index=True, width="stretch")
        c1, c2 = st.columns([3, 1])
        elegida = c1.selectbox("Abrir una atención", [x["id"] for x in h], index=None,
                               format_func=lambda i: next(f"N.º {x['id']} · {u.fecha_txt(x['fecha_atencion'])} · {x['estado']}"
                                                          for x in h if x["id"] == i),
                               placeholder="Elija una atención", key=f"hist_sel_{pid}")
        if c2.button("Abrir en Atención clínica", disabled=elegida is None, key=f"hist_abrir_{pid}"):
            u.ir_a_pagina("Atención clínica", atencion=elegida)


def editar(usuario, p):
    with st.form(f"form_editar_{p['id']}"):
        c1, c2 = st.columns(2)
        nombres = c1.text_input("Nombres", p["nombres"])
        apellidos = c2.text_input("Apellidos", p["apellidos"])
        dni = c1.text_input("DNI (8 dígitos)", p["dni"] or "", max_chars=8)
        sexo = c2.radio("Sexo", ["F", "M"], index=0 if p["sexo"] == "F" else 1, horizontal=True)
        nacimiento = c1.date_input("Fecha de nacimiento", p["fecha_nacimiento"], min_value=date(1900, 1, 1),
                                   max_value=hoy(), format="DD/MM/YYYY")
        telefono = c2.text_input("Teléfono", p["telefono"] or "")
        email = c1.text_input("Correo electrónico", p["email"] or "")
        direccion = c2.text_input("Dirección", p["direccion"] or "")
        nivel = c1.selectbox("Nivel educativo", NIVELES, index=NIVELES.index(p["nivel_educativo"])
                             if p["nivel_educativo"] in NIVELES else 0)
        contacto = c2.text_input("Contacto de emergencia", p["contacto_emergencia"] or "")
        guardar = st.form_submit_button("Guardar cambios", type="primary")
    if guardar:
        cambios = {"nombres": nombres, "apellidos": apellidos, "dni": dni, "sexo": sexo,
                   "fecha_nacimiento": nacimiento, "telefono": telefono, "email": email,
                   "direccion": direccion, "nivel_educativo": nivel, "contacto_emergencia": contacto}
        ok, _ = u.ejecutar(clinico.actualizar_paciente, usuario, p["id"], cambios)
        if ok:
            u.invalidar(f"ficha_{p['id']}")
            u.avisar("Datos del paciente actualizados.")
            st.rerun()


def abrir_caso(usuario, p):
    medicos = u.medicos_activos()
    diag = u.diagnosticos()
    if not medicos:
        st.warning("No hay médicos activos registrados.")
        return
    ids_medicos = list(medicos)
    por_defecto = ids_medicos.index(usuario["id"]) if usuario["id"] in medicos else 0
    with st.form(f"form_caso_{p['id']}"):
        c1, c2 = st.columns(2)
        dx = c1.selectbox("Diagnóstico (CIE-10)", list(diag), format_func=diag.get)
        medico = c2.selectbox("Médico responsable", ids_medicos, format_func=medicos.get, index=por_defecto)
        frecuencia = c1.number_input("Control cada (días)", min_value=1, max_value=365, value=30, step=1)
        plazo = c2.number_input("Plazo de seguimiento actualizado (días; 0 = automático: frecuencia + 15)",
                                min_value=0, max_value=730, value=0, step=1)
        observaciones = st.text_area("Observaciones (opcional)")
        guardar = st.form_submit_button("Abrir caso", type="primary")
    if guardar:
        ok, _ = u.ejecutar(clinico.abrir_caso, usuario, p["id"], dx, medico, int(frecuencia),
                           int(plazo) or None, None, observaciones)
        if ok:
            u.invalidar(f"ficha_{p['id']}")
            u.avisar("Caso de control abierto. Ya puede programar la primera cita.")
            st.rerun()


def programar_cita(usuario, p, caso):
    medicos = u.medicos_activos()
    ids_medicos = list(medicos)
    medico_defecto = ids_medicos.index(caso["medico_id"]) if caso["medico_id"] in medicos else 0
    with st.form(f"form_cita_{p['id']}"):
        c1, c2, c3 = st.columns(3)
        fecha = c1.date_input("Fecha de la cita", hoy(), min_value=hoy(), format="DD/MM/YYYY")
        hora = c2.time_input("Hora", time(9, 0), step=900)
        medico = c3.selectbox("Médico", ids_medicos, format_func=medicos.get, index=medico_defecto) if medicos else None
        canal = st.radio("Enviar el recordatorio por", ["correo", "whatsapp", "sms"], horizontal=True,
                         help="El recordatorio por correo requiere que el paciente tenga un correo registrado.")
        motivo = st.text_input("Motivo", "Control programado")
        guardar = st.form_submit_button("Programar cita", type="primary")
    if guardar:
        ok, _ = u.ejecutar(clinico.programar_cita, usuario, caso["id"], fecha, hora, medico, motivo, canal)
        if ok:
            u.avisar("Cita programada. Se generó su recordatorio (2 días antes, 9:00 a. m.).")
            if canal == "correo" and not p["email"]:
                u.avisar("Este paciente no tiene correo registrado: agréguelo en «Editar datos» para que el "
                         "recordatorio pueda enviarse.", "warning")
            u.invalidar(f"ficha_{p['id']}")
            st.rerun()


def cerrar_caso(usuario, p, caso):
    with st.form(f"form_cierre_{p['id']}"):
        estado = st.radio("Motivo del cierre", ["alta", "abandono"], horizontal=True)
        fecha = st.date_input("Fecha de cierre", hoy(), min_value=caso["fecha_ingreso"], max_value=hoy(),
                              format="DD/MM/YYYY")
        observaciones = st.text_area("Observaciones (opcional)")
        confirmar = st.checkbox("Confirmo que deseo cerrar este caso (se cancelarán sus citas futuras)")
        guardar = st.form_submit_button("Cerrar caso")
    if guardar:
        if not confirmar:
            st.warning("Marque la casilla de confirmación para cerrar el caso.")
            return
        ok, canceladas = u.ejecutar(clinico.cerrar_caso, usuario, caso["id"], estado, fecha, observaciones)
        if ok:
            u.invalidar(f"ficha_{p['id']}")
            u.avisar(f"Caso cerrado por {estado}. Citas futuras canceladas: {canceladas}.")
            st.rerun()


# ----------------------------------------------------------------------
# Registrar paciente nuevo
# ----------------------------------------------------------------------
def registrar(usuario):
    st.subheader("Registrar paciente nuevo")
    st.caption("Los campos con * son obligatorios.")
    with st.form("form_registro", clear_on_submit=False):
        c1, c2 = st.columns(2)
        nombres = c1.text_input("Nombres *")
        apellidos = c2.text_input("Apellidos *")
        dni = c1.text_input("DNI (8 dígitos)", max_chars=8)
        sexo = c2.radio("Sexo *", ["F", "M"], horizontal=True)
        nacimiento = c1.date_input("Fecha de nacimiento *", value=None, min_value=date(1900, 1, 1),
                                   max_value=hoy(), format="DD/MM/YYYY")
        telefono = c2.text_input("Teléfono")
        email = c1.text_input("Correo electrónico (para los recordatorios de cita)")
        direccion = c2.text_input("Dirección")
        nivel = c1.selectbox("Nivel educativo", NIVELES)
        contacto = c2.text_input("Contacto de emergencia (nombre y teléfono)")
        guardar = st.form_submit_button("Registrar paciente", type="primary")
    if guardar:
        if nacimiento is None:
            st.error("La fecha de nacimiento es obligatoria.")
            return
        datos = {"nombres": nombres, "apellidos": apellidos, "dni": dni, "sexo": sexo,
                 "fecha_nacimiento": nacimiento, "telefono": telefono, "email": email,
                 "direccion": direccion, "nivel_educativo": nivel, "contacto_emergencia": contacto}
        ok, nuevo = u.ejecutar(clinico.registrar_paciente, usuario, datos)
        if ok:
            # Se abre su ficha para continuar con el caso de control
            ok2, filas = u.ejecutar(clinico.buscar_pacientes, usuario, nuevo["codigo"])
            if ok2:
                st.session_state["pac_busqueda"] = filas
            st.session_state["_destino_pac_seccion"] = "Buscar paciente"
            st.session_state["_destino_pac_sel"] = nuevo["id"]
            u.avisar(f"Paciente registrado con el código {nuevo['codigo']}. Ahora puede abrir su caso de control.")
            st.rerun()
