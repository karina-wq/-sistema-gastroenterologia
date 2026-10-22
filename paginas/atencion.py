"""Atención clínica: formulario del control con la lista de verificación del protocolo,
procedimientos, exámenes, eventos adversos y encuesta de satisfacción."""
from datetime import datetime, time

import streamlit as st

from sistema import base, clinico
from sistema.base import hoy
from . import utilidades as u

# Si es True, una atención incompleta NO se puede finalizar. Se deja en False porque, si el
# sistema bloqueara la finalización, el indicador de "registros completos" siempre sería 100 %
# y dejaría de medir algo (decisión de diseño de la Fase 2; conviene confirmarla con el asesor).
EXIGIR_COMPLETO = False

TIPOS_PROCEDIMIENTO = ["endoscopia digestiva alta", "colonoscopia", "CPRE", "otro"]
TIPOS_EXAMEN = ["laboratorio", "patologia", "imagen", "otro"]
TIPOS_EVENTO = ["Sangrado posbiopsia", "Reacción a la sedación", "Dolor abdominal posprocedimiento",
                "Pancreatitis pos-CPRE", "Reacción adversa a medicamento", "Caída del paciente en consultorio",
                "Otro (describir)"]
GRAVEDADES = ["leve", "moderado", "grave", "mortal"]
ETIQUETA = {"programada": "Programada", "asistio": "Asistió", "inasistio": "No asistió"}


def mostrar(usuario):
    st.title("Atención clínica")

    # Otra pantalla (agenda o historial) puede pedir abrir una atención o una cita concreta
    abrir = st.session_state.pop("_destino_atencion", None)
    if abrir:
        st.session_state["at_id"] = abrir
    if "_destino_fecha" in st.session_state:
        st.session_state["at_fecha"] = st.session_state.pop("_destino_fecha")
        st.session_state.pop("at_id", None)
    if "_destino_cita" in st.session_state:
        st.session_state["_at_cita_pre"] = st.session_state.pop("_destino_cita")

    if st.session_state.get("at_id"):
        espacio_de_trabajo(usuario, st.session_state["at_id"])
    else:
        lista_de_citas(usuario)


# ----------------------------------------------------------------------
# 1. Elegir la cita
# ----------------------------------------------------------------------
def lista_de_citas(usuario):
    if not u.tiene(usuario, "citas.gestionar"):
        st.info("Su rol no puede listar citas. Abra una atención desde el historial del paciente.")
        return
    st.session_state.setdefault("at_fecha", hoy())
    fecha = st.date_input("Fecha de las citas", key="at_fecha", format="DD/MM/YYYY")
    ok, citas = u.ejecutar(clinico.listar_citas, usuario, fecha, fecha)
    if not ok:
        return
    citas = [c for c in citas if c["estado"] in ("programada", "asistio")]
    if not citas:
        st.info("No hay citas vigentes para esa fecha.")
        return

    # ¿Qué citas ya tienen atención? (solo estado, no contenido clínico)
    meta = {m["cita_id"]: m for m in base.consultar(
        "SELECT id, cita_id, estado FROM atenciones WHERE cita_id = ANY(%s)", ([c["id"] for c in citas],))}

    def etiqueta(cid):
        c = next(x for x in citas if x["id"] == cid)
        a = meta.get(cid)
        situacion = f"atención {a['estado']}" if a else ETIQUETA.get(c["estado"], c["estado"])
        return f"{u.hora_txt(c['hora_programada'])} · {c['paciente']} · {situacion}"

    ids = [c["id"] for c in citas]
    pre = st.session_state.pop("_at_cita_pre", None)
    if pre in ids:
        st.session_state["at_cita"] = pre
    cid = st.selectbox("Cita", ids, format_func=etiqueta, index=None, placeholder="Elija una cita", key="at_cita")
    if not cid:
        return

    cita = next(c for c in citas if c["id"] == cid)
    st.markdown(f"**Paciente:** {cita['paciente']} ({cita['codigo']}) · **Médico:** {cita['medico'] or '—'}")
    existente = meta.get(cid)
    if existente:
        if st.button("Abrir la atención", type="primary", key=f"at_abrir_{cid}"):
            st.session_state["at_id"] = existente["id"]
            st.rerun()
    elif u.tiene(usuario, "atenciones.registrar"):
        with st.form(f"form_iniciar_{cid}"):
            llegada = st.time_input("Hora de llegada del paciente", base.ahora().time().replace(second=0, microsecond=0),
                                    step=300, help="De la hora de llegada a la hora de inicio se calcula el tiempo de espera.")
            iniciar = st.form_submit_button("Iniciar atención", type="primary")
        if iniciar:
            momento = datetime.combine(hoy(), llegada, base.TZ)
            if momento > base.ahora():
                st.error("La hora de llegada no puede ser futura.")
            else:
                ok, atencion_id = u.ejecutar(clinico.iniciar_atencion, usuario, cid, momento)
                if ok:
                    st.session_state["at_id"] = atencion_id
                    st.rerun()
    else:
        st.info("Esta cita todavía no tiene atención. Solo el médico puede iniciarla.")


# ----------------------------------------------------------------------
# 2. Trabajar la atención
# ----------------------------------------------------------------------
def espacio_de_trabajo(usuario, aid):
    if st.button("← Volver a la lista de citas"):
        u.invalidar(f"atencion_{aid}", "hist_", "ficha_")
        st.session_state.pop("at_id", None)
        st.rerun()

    a = u.leer_cache(f"atencion_{aid}", clinico.obtener_atencion, usuario, aid)   # registra "VER" una sola vez
    if a is None:
        st.session_state.pop("at_id", None)
        return

    finalizada = a["estado"] == "finalizada"
    st.subheader(f"{a['paciente']} · {a['paciente_codigo']}")
    c1, c2, c3 = st.columns(3)
    c1.metric("Estado", "Finalizada" if finalizada else "Borrador")
    c2.metric("Fecha", u.fecha_txt(a["fecha_atencion"]))
    c3.metric("Registro completo", "Sí" if a["registro_completo"] else "No")
    st.caption(f"Médico: {a['medico']} · Diagnóstico: {a['diagnostico'] or '—'} · "
               f"Llegada {u.hora_txt(a['hora_llegada'])} · Inicio {u.hora_txt(a['hora_inicio_atencion'])} · "
               f"Fin {u.hora_txt(a['hora_fin_atencion'])}")
    if finalizada and not a["registro_completo"]:
        st.warning("Faltan campos obligatorios: " + ", ".join(a["campos_faltantes"]))

    puede_editar = u.tiene(usuario, "atenciones.registrar")
    if finalizada:
        resumen(a)
        if puede_editar and a["medico_id"] == usuario["id"]:
            with st.expander("Reabrir para corregir"):
                with st.form(f"form_reabrir_{aid}"):
                    motivo = st.text_input("Motivo de la reapertura (obligatorio)")
                    guardar = st.form_submit_button("Reabrir atención")
                if guardar:
                    ok, _ = u.ejecutar(clinico.reabrir_atencion, usuario, aid, motivo)
                    if ok:
                        u.invalidar(f"atencion_{aid}", "hist_", "ficha_")
                        u.avisar("Atención reabierta; el motivo quedó en la bitácora.", "warning")
                        st.rerun()
    elif puede_editar:
        formulario(usuario, a)
    else:
        resumen(a)
        st.info("Su rol puede consultar la atención y registrar eventos adversos o la encuesta, pero no editar el contenido clínico.")

    st.divider()
    complementos(usuario, a)


def resumen(a):
    """Vista de solo lectura del contenido clínico."""
    st.markdown(f"**Motivo de consulta:** {a['motivo_consulta'] or '—'}")
    st.markdown(f"**Anamnesis:** {a['anamnesis'] or '—'}")
    st.markdown(f"**Examen físico:** {a['examen_fisico'] or '—'}")
    st.markdown(f"**Tratamiento:** {a['tratamiento'] or '—'}")
    st.markdown(f"**Indicaciones:** {a['indicaciones'] or '—'}")
    if a["observaciones"]:
        st.markdown(f"**Observaciones:** {a['observaciones']}")
    st.markdown("**Protocolo:**")
    for p in a["pasos"]:
        st.markdown(f"- {'✅' if p['cumplido'] else '⬜'} {p['orden']}. {p['descripcion']}")


def formulario(usuario, a):
    aid = a["id"]
    diag = u.diagnosticos()
    codigos = list(diag)
    with st.form(f"form_atencion_{aid}"):
        motivo = st.text_area("Motivo de consulta", a["motivo_consulta"] or "")
        anamnesis = st.text_area("Anamnesis", a["anamnesis"] or "")
        examen = st.text_area("Examen físico", a["examen_fisico"] or "")
        dx = st.selectbox("Diagnóstico (CIE-10)", codigos, format_func=diag.get,
                          index=codigos.index(a["diagnostico_cie10"]) if a["diagnostico_cie10"] in codigos else None)
        tratamiento = st.text_area("Tratamiento", a["tratamiento"] or "")
        indicaciones = st.text_area("Indicaciones al paciente", a["indicaciones"] or "")
        observaciones = st.text_area("Observaciones (opcional)", a["observaciones"] or "")

        st.markdown("**Lista de verificación del protocolo**")
        pasos = {}
        for p in a["pasos"]:
            texto = f"{p['orden']}. {p['descripcion']}" + ("  *(obligatorio)*" if p["obligatorio"] else "")
            pasos[p["paso_id"]] = st.checkbox(texto, value=p["cumplido"], key=f"paso_{aid}_{p['paso_id']}")

        b1, b2 = st.columns(2)
        guardar = b1.form_submit_button("Guardar borrador", width="stretch")
        finalizar = b2.form_submit_button("Finalizar atención", type="primary", width="stretch")

    if guardar or finalizar:
        datos = {"motivo_consulta": motivo, "anamnesis": anamnesis, "examen_fisico": examen,
                 "diagnostico_cie10": dx, "tratamiento": tratamiento, "indicaciones": indicaciones,
                 "observaciones": observaciones}
        ok, r = u.ejecutar(clinico.guardar_atencion, usuario, aid, datos, pasos,
                           finalizar=finalizar, exigir_completo=EXIGIR_COMPLETO)
        if ok:
            u.invalidar(f"atencion_{aid}", "hist_", "ficha_")
            if finalizar and r["registro_completo"]:
                u.avisar("Atención finalizada con el registro completo.")
            elif finalizar:
                u.avisar("Atención finalizada, pero faltan campos obligatorios: " + ", ".join(r["campos_faltantes"])
                         + ". Puede reabrirla para completarlos.", "warning")
            else:
                u.avisar("Borrador guardado.")
            st.rerun()
        else:
            # Si se exigía el registro completo, los datos igual quedaron guardados como borrador
            u.invalidar(f"atencion_{aid}", "hist_", "ficha_")


# ----------------------------------------------------------------------
# 3. Procedimientos, exámenes, eventos adversos, encuesta
# ----------------------------------------------------------------------
def complementos(usuario, a):
    aid = a["id"]
    seccion = st.radio("Complementos", ["Procedimientos", "Exámenes", "Eventos adversos", "Encuesta de satisfacción"],
                       horizontal=True, label_visibility="collapsed", key="at_complemento")

    if seccion == "Procedimientos":
        if a["procedimientos"]:
            st.dataframe(u.a_df(a["procedimientos"], ["tipo", "fecha", "hallazgos", "conclusion"],
                                {"tipo": "Tipo", "fecha": "Fecha", "hallazgos": "Hallazgos", "conclusion": "Conclusión"}),
                         hide_index=True, width="stretch")
        else:
            st.caption("Sin procedimientos registrados.")
        if u.tiene(usuario, "atenciones.registrar"):
            with st.form(f"form_proc_{aid}", clear_on_submit=True):
                tipo = st.selectbox("Tipo de procedimiento", TIPOS_PROCEDIMIENTO)
                hallazgos = st.text_area("Hallazgos")
                conclusion = st.text_area("Conclusión")
                guardar = st.form_submit_button("Agregar procedimiento")
            if guardar:
                ok, _ = u.ejecutar(clinico.registrar_procedimiento, usuario, aid, tipo, hallazgos, conclusion)
                if ok:
                    u.invalidar(f"atencion_{aid}", "hist_", "ficha_")
                    u.avisar("Procedimiento agregado.")
                    st.rerun()

    elif seccion == "Exámenes":
        if a["examenes"]:
            st.dataframe(u.a_df(a["examenes"], ["tipo", "nombre_examen", "resultado", "valor_numerico", "unidad", "fecha"],
                                {"tipo": "Tipo", "nombre_examen": "Examen", "resultado": "Resultado",
                                 "valor_numerico": "Valor", "unidad": "Unidad", "fecha": "Fecha"}),
                         hide_index=True, width="stretch")
        else:
            st.caption("Sin exámenes registrados.")
        if u.tiene(usuario, "atenciones.registrar"):
            with st.form(f"form_examen_{aid}", clear_on_submit=True):
                c1, c2 = st.columns(2)
                tipo = c1.selectbox("Tipo", TIPOS_EXAMEN)
                nombre = c2.text_input("Nombre del examen (ej. Hemoglobina)")
                resultado = st.text_input("Resultado")
                c3, c4 = st.columns(2)
                valor = c3.text_input("Valor numérico (opcional)")
                unidad = c4.text_input("Unidad (opcional)")
                guardar = st.form_submit_button("Agregar examen")
            if guardar:
                try:
                    numero = float(valor.replace(",", ".")) if valor.strip() else None
                except ValueError:
                    st.error("El valor numérico debe ser un número (ej. 12.5).")
                else:
                    ok, _ = u.ejecutar(clinico.registrar_examen, usuario, aid, tipo, nombre, resultado, numero, unidad)
                    if ok:
                        u.invalidar(f"atencion_{aid}", "hist_", "ficha_")
                        u.avisar("Examen agregado.")
                        st.rerun()

    elif seccion == "Eventos adversos":
        if a["eventos_adversos"]:
            st.dataframe(u.a_df(a["eventos_adversos"], ["fecha_evento", "tipo", "gravedad", "descripcion", "accion_tomada"],
                                {"fecha_evento": "Fecha", "tipo": "Tipo", "gravedad": "Gravedad",
                                 "descripcion": "Descripción", "accion_tomada": "Acción tomada"}),
                         hide_index=True, width="stretch")
        else:
            st.caption("Sin eventos adversos registrados en esta atención.")
        if u.tiene(usuario, "eventos.registrar"):
            procs = {p["id"]: f"{p['tipo']} ({u.fecha_txt(p['fecha'])})" for p in a["procedimientos"]}
            with st.form(f"form_evento_{aid}", clear_on_submit=True):
                c1, c2 = st.columns(2)
                tipo = c1.selectbox("Tipo de evento", TIPOS_EVENTO)
                gravedad = c2.selectbox("Gravedad", GRAVEDADES)
                otro = st.text_input("Si eligió «Otro», escriba el tipo de evento")
                descripcion = st.text_area("Descripción")
                accion = st.text_area("Acción tomada")
                proc = st.selectbox("Procedimiento relacionado (opcional)", [None] + list(procs),
                                    format_func=lambda i: "Ninguno" if i is None else procs[i])
                guardar = st.form_submit_button("Registrar evento adverso", type="primary")
            if guardar:
                tipo_final = otro if tipo.startswith("Otro") else tipo
                ok, _ = u.ejecutar(clinico.registrar_evento_adverso, usuario, aid, tipo_final, gravedad,
                                   descripcion, proc, accion)
                if ok:
                    u.invalidar(f"atencion_{aid}", "hist_", "ficha_")
                    u.avisar("Evento adverso registrado.", "warning")
                    st.rerun()

    else:
        enc = a["encuesta"]
        if enc:
            st.write(f"Puntaje: **{enc['puntaje']} / 5** · Tiempo de espera aceptable: "
                     f"**{'Sí' if enc['tiempo_espera_aceptable'] else 'No' if enc['tiempo_espera_aceptable'] is not None else '—'}**")
            if enc.get("comentario"):
                st.write(f"Comentario: {enc['comentario']}")
        elif u.tiene(usuario, "citas.gestionar"):
            with st.form(f"form_encuesta_{aid}", clear_on_submit=True):
                puntaje = st.radio("¿Cómo califica la atención recibida? (1 = muy mala, 5 = muy buena)",
                                   [1, 2, 3, 4, 5], index=4, horizontal=True)
                espera = st.checkbox("El tiempo de espera fue aceptable", value=True)
                comentario = st.text_input("Comentario (opcional)")
                guardar = st.form_submit_button("Guardar encuesta")
            if guardar:
                ok, _ = u.ejecutar(clinico.registrar_encuesta, usuario, aid, int(puntaje), bool(espera), comentario)
                if ok:
                    u.invalidar(f"atencion_{aid}", "hist_", "ficha_")
                    u.avisar("Encuesta registrada. ¡Gracias!")
                    st.rerun()
        else:
            st.caption("Sin encuesta registrada.")
