"""Lógica clínica: pacientes, casos, citas, recordatorios, atenciones, eventos adversos y encuestas."""
import re
import uuid
from datetime import datetime, time, timedelta
 
import psycopg2
 
from .base import (transaccion, requiere, registrar_auditoria, ErrorValidacion, NoEncontrado,
                   TZ, ahora, hoy, a_fecha, texto, exigir, uno)
 
CAMPOS_PACIENTE = ["nombres", "apellidos", "fecha_nacimiento", "sexo", "dni", "telefono", "email",
                   "direccion", "nivel_educativo", "contacto_emergencia"]
CAMPOS_ATENCION = ["motivo_consulta", "anamnesis", "examen_fisico", "diagnostico_cie10", "tratamiento",
                   "indicaciones", "observaciones", "hora_llegada", "hora_inicio_atencion", "hora_fin_atencion"]
 
 
# ======================================================================
# PACIENTES
# ======================================================================
def _validar_paciente(d, parcial=False):
    """Valida y normaliza los datos de un paciente."""
    limpio = {}
    for campo in CAMPOS_PACIENTE:
        if campo not in d:
            if not parcial and campo in ("nombres", "apellidos", "fecha_nacimiento", "sexo"):
                raise ErrorValidacion(f"El campo «{campo}» es obligatorio.")
            continue
        limpio[campo] = texto(d[campo]) if campo != "fecha_nacimiento" else d[campo]
    if "fecha_nacimiento" in limpio:
        f = a_fecha(limpio["fecha_nacimiento"], "fecha_nacimiento")
        if f >= hoy():
            raise ErrorValidacion("La fecha de nacimiento debe ser anterior a hoy.")
        limpio["fecha_nacimiento"] = f
    if "sexo" in limpio:
        limpio["sexo"] = (limpio["sexo"] or "").upper()
        if limpio["sexo"] not in ("M", "F"):
            raise ErrorValidacion("El sexo debe ser M o F.")
    if limpio.get("dni") and not re.fullmatch(r"\d{8}", limpio["dni"]):
        raise ErrorValidacion("El DNI debe tener 8 dígitos.")
    for obligatorio in ("nombres", "apellidos"):
        if obligatorio in limpio and not limpio[obligatorio]:
            raise ErrorValidacion(f"El campo «{obligatorio}» es obligatorio.")
    return limpio
 
 
@requiere("pacientes.editar")
def registrar_paciente(usuario, datos):
    """Crea un paciente y le asigna un código P-00001. Devuelve {'id', 'codigo'}."""
    d = _validar_paciente(datos)
    try:
        with transaccion(usuario["id"]) as cur:
            cur.execute(
                """INSERT INTO pacientes (codigo, dni, nombres, apellidos, fecha_nacimiento, sexo, telefono, email,
                                          direccion, nivel_educativo, contacto_emergencia, created_by)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id""",
                ("TMP-" + uuid.uuid4().hex[:12], d.get("dni"), d["nombres"], d["apellidos"], d["fecha_nacimiento"],
                 d["sexo"], d.get("telefono"), d.get("email"), d.get("direccion"), d.get("nivel_educativo"),
                 d.get("contacto_emergencia"), usuario["id"]))
            pid = cur.fetchone()["id"]
            codigo = f"P-{pid:05d}"
            cur.execute("UPDATE pacientes SET codigo = %s WHERE id = %s", (codigo, pid))
            return {"id": pid, "codigo": codigo}
    except psycopg2.errors.UniqueViolation:
        raise ErrorValidacion("Ya existe un paciente con ese DNI.")
 
 
@requiere("pacientes.editar")
def actualizar_paciente(usuario, paciente_id, cambios):
    d = _validar_paciente(cambios, parcial=True)
    if not d:
        raise ErrorValidacion("No hay cambios que guardar.")
    sets = ", ".join(f"{c} = %s" for c in d)
    try:
        with transaccion(usuario["id"]) as cur:
            uno(cur, "SELECT id FROM pacientes WHERE id = %s", (paciente_id,), "El paciente no existe.")
            cur.execute(f"UPDATE pacientes SET {sets} WHERE id = %s", (*d.values(), paciente_id))
    except psycopg2.errors.UniqueViolation:
        raise ErrorValidacion("Ya existe otro paciente con ese DNI.")
 
 
@requiere("pacientes.ver")
def buscar_pacientes(usuario, consulta, limite=50):
    """Busca por nombre, apellido, DNI o código. Deja constancia en la bitácora."""
    consulta = exigir(consulta, "búsqueda")
    patron = f"%{consulta}%"
    with transaccion(usuario["id"]) as cur:
        cur.execute(
            """SELECT id, codigo, dni, nombres, apellidos, sexo, telefono,
                      date_part('year', age(fecha_nacimiento))::int AS edad, activo
               FROM pacientes
               WHERE (nombres || ' ' || apellidos) ILIKE %s OR dni ILIKE %s OR codigo ILIKE %s
               ORDER BY apellidos, nombres LIMIT %s""", (patron, patron, patron, limite))
        filas = cur.fetchall()
        registrar_auditoria(cur, usuario, "BUSCAR", "pacientes", None, {"texto": consulta, "resultados": len(filas)})
        return filas
 
 
@requiere("pacientes.ver")
def obtener_paciente(usuario, paciente_id):
    """Ficha del paciente con sus casos. Deja constancia de la lectura (VER)."""
    with transaccion(usuario["id"]) as cur:
        paciente = uno(cur, "SELECT * FROM pacientes WHERE id = %s", (paciente_id,), "El paciente no existe.")
        cur.execute("""SELECT k.*, c.descripcion AS diagnostico FROM casos_control k
                       LEFT JOIN cie10 c ON c.codigo = k.diagnostico_cie10
                       WHERE k.paciente_id = %s ORDER BY k.fecha_ingreso DESC""", (paciente_id,))
        paciente["casos"] = cur.fetchall()
        registrar_auditoria(cur, usuario, "VER", "pacientes", paciente_id)
        return paciente
 
 
def listar_diagnosticos():
    """Catálogo CIE-10 para los selectores de la interfaz."""
    with transaccion() as cur:
        cur.execute("SELECT codigo, descripcion FROM cie10 ORDER BY codigo")
        return cur.fetchall()
 
 
# ======================================================================
# CASOS EN CONTROL
# ======================================================================
@requiere("pacientes.editar")
def abrir_caso(usuario, paciente_id, diagnostico_cie10, medico_id, frecuencia_control_dias=30,
               plazo_actualizacion_dias=None, fecha_ingreso=None, observaciones=None):
    """Incorpora al paciente al programa de control. Un paciente solo puede tener un caso activo."""
    if int(frecuencia_control_dias) <= 0:
        raise ErrorValidacion("La frecuencia de control debe ser mayor que 0 días.")
    plazo = int(plazo_actualizacion_dias) if plazo_actualizacion_dias else int(frecuencia_control_dias) + 15
    ingreso = a_fecha(fecha_ingreso, "fecha de ingreso") if fecha_ingreso else hoy()
    with transaccion(usuario["id"]) as cur:
        uno(cur, "SELECT id FROM pacientes WHERE id = %s", (paciente_id,), "El paciente no existe.")
        uno(cur, "SELECT codigo FROM cie10 WHERE codigo = %s", (diagnostico_cie10,), "El diagnóstico CIE-10 no existe.")
        uno(cur, "SELECT id FROM usuarios WHERE id = %s AND activo", (medico_id,), "El médico no existe o está inactivo.")
        cur.execute("SELECT id FROM casos_control WHERE paciente_id = %s AND estado = 'en_seguimiento'", (paciente_id,))
        if cur.fetchone():
            raise ErrorValidacion("El paciente ya tiene un caso en seguimiento.")
        cur.execute(
            """INSERT INTO casos_control (paciente_id, diagnostico_cie10, medico_id, fecha_ingreso,
                                          frecuencia_control_dias, plazo_actualizacion_dias, observaciones)
               VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id""",
            (paciente_id, diagnostico_cie10, medico_id, ingreso, int(frecuencia_control_dias), plazo, texto(observaciones)))
        return cur.fetchone()["id"]
 
 
@requiere("atenciones.registrar")
def cerrar_caso(usuario, caso_id, estado, fecha_cierre=None, observaciones=None):
    """Cierra el caso por alta o abandono y cancela sus citas futuras. Devuelve cuántas canceló."""
    if estado not in ("alta", "abandono"):
        raise ErrorValidacion("El estado de cierre debe ser 'alta' o 'abandono'.")
    with transaccion(usuario["id"]) as cur:
        caso = uno(cur, "SELECT * FROM casos_control WHERE id = %s", (caso_id,), "El caso no existe.")
        if caso["estado"] != "en_seguimiento":
            raise ErrorValidacion("El caso ya está cerrado.")
        cierre = a_fecha(fecha_cierre, "fecha de cierre") if fecha_cierre else hoy()
        if cierre < caso["fecha_ingreso"]:
            raise ErrorValidacion("La fecha de cierre no puede ser anterior al ingreso.")
        cur.execute("""UPDATE casos_control SET estado = %s, fecha_cierre = %s,
                       observaciones = COALESCE(%s, observaciones) WHERE id = %s""",
                    (estado, cierre, texto(observaciones), caso_id))
        cur.execute("UPDATE citas_control SET estado = 'cancelada' WHERE caso_id = %s AND estado = 'programada'",
                    (caso_id,))
        return cur.rowcount
 
 
# ======================================================================
# CITAS Y RECORDATORIOS
# ======================================================================
def _insertar_cita(cur, caso, fecha, hora, medico_id, motivo, canal="whatsapp"):
    """Crea la cita y su recordatorio (2 días antes, 9:00 a. m.; si ya pasó, se envía de inmediato)."""
    cur.execute(
        """SELECT id FROM citas_control
           WHERE caso_id = %s AND fecha_programada = %s AND estado = 'programada'""", (caso["id"], fecha))
    if cur.fetchone():
        raise ErrorValidacion("El caso ya tiene una cita programada para esa fecha.")
    cur.execute(
        """INSERT INTO citas_control (caso_id, paciente_id, medico_id, fecha_programada, hora_programada, motivo)
           VALUES (%s, %s, %s, %s, %s, %s) RETURNING id""",
        (caso["id"], caso["paciente_id"], medico_id or caso["medico_id"], fecha, hora, motivo))
    cita_id = cur.fetchone()["id"]
    programado = max(ahora(), datetime.combine(fecha - timedelta(days=2), time(9, 0), TZ))
    cur.execute("INSERT INTO recordatorios (cita_id, canal, programado_para) VALUES (%s, %s, %s)",
                (cita_id, canal, programado))
    return cita_id
 
 
@requiere("citas.gestionar")
def programar_cita(usuario, caso_id, fecha, hora=None, medico_id=None, motivo="Control programado", canal="whatsapp"):
    fecha = a_fecha(fecha, "fecha de la cita")
    if fecha < hoy():
        raise ErrorValidacion("No se puede programar una cita en una fecha pasada.")
    if canal not in ("whatsapp", "sms", "correo"):
        raise ErrorValidacion("Canal de recordatorio inválido.")
    with transaccion(usuario["id"]) as cur:
        caso = uno(cur, "SELECT * FROM casos_control WHERE id = %s", (caso_id,), "El caso no existe.")
        if caso["estado"] != "en_seguimiento":
            raise ErrorValidacion("El caso está cerrado; no admite nuevas citas.")
        return _insertar_cita(cur, caso, fecha, hora, medico_id, motivo, canal)
 
 
@requiere("citas.gestionar")
def registrar_asistencia(usuario, cita_id, fecha_asistencia=None):
    """Marca que el paciente asistió (un trigger actualiza la fecha del último control del caso)."""
    fecha = a_fecha(fecha_asistencia, "fecha de asistencia") if fecha_asistencia else hoy()
    if fecha > hoy():
        raise ErrorValidacion("La fecha de asistencia no puede ser futura.")
    with transaccion(usuario["id"]) as cur:
        cita = uno(cur, "SELECT * FROM citas_control WHERE id = %s", (cita_id,), "La cita no existe.")
        if cita["estado"] not in ("programada", "inasistio"):
            raise ErrorValidacion(f"La cita está en estado «{cita['estado']}» y no admite asistencia.")
        cur.execute("UPDATE citas_control SET estado = 'asistio', fecha_asistencia = %s WHERE id = %s", (fecha, cita_id))
 
 
@requiere("citas.gestionar")
def marcar_inasistencia(usuario, cita_id):
    with transaccion(usuario["id"]) as cur:
        cita = uno(cur, "SELECT * FROM citas_control WHERE id = %s", (cita_id,), "La cita no existe.")
        if cita["estado"] != "programada":
            raise ErrorValidacion("Solo una cita programada puede marcarse como inasistencia.")
        if cita["fecha_programada"] > hoy():
            raise ErrorValidacion("La cita aún no ocurre; no puede marcarse como inasistencia.")
        cur.execute("UPDATE citas_control SET estado = 'inasistio' WHERE id = %s", (cita_id,))
 
 
@requiere("citas.gestionar")
def reprogramar_cita(usuario, cita_id, nueva_fecha, nueva_hora=None, canal="whatsapp"):
    """La cita original queda 'reprogramada' y se crea una nueva. Devuelve el id de la nueva."""
    nueva_fecha = a_fecha(nueva_fecha, "nueva fecha")
    if nueva_fecha < hoy():
        raise ErrorValidacion("La nueva fecha no puede ser pasada.")
    with transaccion(usuario["id"]) as cur:
        cita = uno(cur, "SELECT * FROM citas_control WHERE id = %s", (cita_id,), "La cita no existe.")
        if cita["estado"] != "programada":
            raise ErrorValidacion("Solo una cita programada puede reprogramarse.")
        caso = uno(cur, "SELECT * FROM casos_control WHERE id = %s", (cita["caso_id"],))
        cur.execute("UPDATE citas_control SET estado = 'reprogramada' WHERE id = %s", (cita_id,))
        return _insertar_cita(cur, caso, nueva_fecha, nueva_hora or cita["hora_programada"],
                              cita["medico_id"], "Control reprogramado", canal)
 
 
@requiere("citas.gestionar")
def cancelar_cita(usuario, cita_id, motivo=None):
    with transaccion(usuario["id"]) as cur:
        cita = uno(cur, "SELECT * FROM citas_control WHERE id = %s", (cita_id,), "La cita no existe.")
        if cita["estado"] != "programada":
            raise ErrorValidacion("Solo una cita programada puede cancelarse.")
        cur.execute("UPDATE citas_control SET estado = 'cancelada', motivo = COALESCE(%s, motivo) WHERE id = %s",
                    (texto(motivo), cita_id))
 
 
@requiere("citas.gestionar")
def listar_citas(usuario, desde=None, hasta=None, estado=None, medico_id=None, limite=500):
    desde = a_fecha(desde, "desde") if desde else hoy()
    hasta = a_fecha(hasta, "hasta") if hasta else desde
    cond, params = ["c.fecha_programada BETWEEN %s AND %s"], [desde, hasta]
    if estado:
        cond.append("c.estado = %s")
        params.append(estado)
    if medico_id:
        cond.append("c.medico_id = %s")
        params.append(medico_id)
    with transaccion() as cur:
        cur.execute(f"""SELECT c.id, c.fecha_programada, c.hora_programada, c.estado, c.caso_id, c.paciente_id,
                               p.codigo, p.nombres || ' ' || p.apellidos AS paciente, p.telefono,
                               u.nombres || ' ' || u.apellidos AS medico
                        FROM citas_control c
                        JOIN pacientes p ON p.id = c.paciente_id
                        LEFT JOIN usuarios u ON u.id = c.medico_id
                        WHERE {' AND '.join(cond)}
                        ORDER BY c.fecha_programada, c.hora_programada LIMIT %s""", (*params, limite))
        return cur.fetchall()
 
 
@requiere("pacientes.ver")
def alertas_seguimiento(usuario):
    """Casos en seguimiento con el control vencido (vista v_alertas_seguimiento)."""
    with transaccion() as cur:
        cur.execute("SELECT * FROM v_alertas_seguimiento ORDER BY dias_vencido DESC")
        return cur.fetchall()
 
 
@requiere("pacientes.ver")
def pacientes_inasistentes(usuario, dias=60):
    """Pacientes de casos activos que faltaron a una cita en los últimos N días."""
    with transaccion() as cur:
        cur.execute("""SELECT p.id AS paciente_id, p.codigo, p.nombres || ' ' || p.apellidos AS paciente, p.telefono,
                              count(*) AS inasistencias, max(c.fecha_programada) AS ultima_inasistencia
                       FROM citas_control c
                       JOIN casos_control k ON k.id = c.caso_id AND k.estado = 'en_seguimiento'
                       JOIN pacientes p ON p.id = c.paciente_id
                       WHERE c.estado = 'inasistio' AND c.fecha_programada >= CURRENT_DATE - %s
                       GROUP BY p.id, p.codigo, p.nombres, p.apellidos, p.telefono
                       ORDER BY max(c.fecha_programada) DESC""", (int(dias),))
        return cur.fetchall()
 
 
@requiere("citas.gestionar")
def recordatorios_pendientes(usuario):
    """Recordatorios cuya hora de envío ya llegó y aún no se enviaron."""
    with transaccion() as cur:
        cur.execute("""SELECT r.id, r.canal, r.programado_para, c.fecha_programada, c.hora_programada,
                              p.nombres || ' ' || p.apellidos AS paciente, p.telefono, p.email
                       FROM recordatorios r
                       JOIN citas_control c ON c.id = r.cita_id AND c.estado = 'programada'
                       JOIN pacientes p ON p.id = c.paciente_id
                       WHERE r.estado = 'pendiente' AND r.programado_para <= now()
                       ORDER BY r.programado_para""")
        return cur.fetchall()
 
 
def mensaje_recordatorio(r):
    """Texto del recordatorio (el envío real por WhatsApp/SMS/correo se integra después)."""
    hora = f" a las {r['hora_programada']:%H:%M}" if r.get("hora_programada") else ""
    return (f"Hola {r['paciente']}, le recordamos su control de Gastroenterología en el Hospital Nacional "
            f"Arzobispo Loayza el {r['fecha_programada']:%d/%m/%Y}{hora}. "
            f"Si no puede asistir, comuníquese para reprogramar su cita.")
 
 
@requiere("citas.gestionar")
def marcar_recordatorio(usuario, recordatorio_id, enviado=True):
    with transaccion(usuario["id"]) as cur:
        uno(cur, "SELECT id FROM recordatorios WHERE id = %s", (recordatorio_id,), "El recordatorio no existe.")
        cur.execute("UPDATE recordatorios SET estado = %s, enviado_en = CASE WHEN %s THEN now() END WHERE id = %s",
                    ("enviado" if enviado else "fallido", bool(enviado), recordatorio_id))
 
 
# ======================================================================
# ATENCIONES (historia clínica del control)
# ======================================================================
def protocolo_activo():
    """Protocolo de atención vigente y sus pasos (para la lista de verificación del formulario)."""
    with transaccion() as cur:
        prot = uno(cur, "SELECT * FROM protocolos_atencion WHERE activo ORDER BY id LIMIT 1",
                   None, "No hay un protocolo de atención activo.")
        cur.execute("SELECT id, orden, descripcion, obligatorio FROM protocolo_pasos WHERE protocolo_id = %s ORDER BY orden",
                    (prot["id"],))
        prot["pasos"] = cur.fetchall()
        return prot
 
 
@requiere("atenciones.registrar")
def iniciar_atencion(usuario, cita_id, hora_llegada=None):
    """Abre la atención (borrador) de una cita. Si la cita estaba programada, la marca como asistida.
    Si ya existe la atención de esa cita, devuelve su id."""
    with transaccion(usuario["id"]) as cur:
        cita = uno(cur, "SELECT * FROM citas_control WHERE id = %s", (cita_id,), "La cita no existe.")
        cur.execute("SELECT id FROM atenciones WHERE cita_id = %s", (cita_id,))
        existente = cur.fetchone()
        if existente:
            return existente["id"]
        if cita["estado"] == "programada":
            if cita["fecha_programada"] > hoy():
                raise ErrorValidacion("La cita es futura; aún no se puede iniciar la atención.")
            cur.execute("UPDATE citas_control SET estado = 'asistio', fecha_asistencia = %s WHERE id = %s",
                        (hoy(), cita_id))
            fecha_atencion = hoy()
        elif cita["estado"] == "asistio":
            fecha_atencion = cita["fecha_asistencia"]
        else:
            raise ErrorValidacion(f"La cita está en estado «{cita['estado']}»; no admite atención.")
        caso = uno(cur, "SELECT * FROM casos_control WHERE id = %s", (cita["caso_id"],))
        prot = uno(cur, "SELECT id FROM protocolos_atencion WHERE activo ORDER BY id LIMIT 1",
                   None, "No hay un protocolo de atención activo.")
        cur.execute(
            """INSERT INTO atenciones (cita_id, caso_id, paciente_id, medico_id, protocolo_id, fecha_atencion,
                                       hora_llegada, diagnostico_cie10, estado)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'borrador') RETURNING id""",
            (cita_id, caso["id"], caso["paciente_id"], usuario["id"], prot["id"], fecha_atencion,
             hora_llegada or ahora(), caso["diagnostico_cie10"]))
        return cur.fetchone()["id"]
 
 
@requiere("atenciones.registrar")
def guardar_atencion(usuario, atencion_id, datos, pasos_cumplidos=None, finalizar=False, exigir_completo=False):
    """Guarda los campos clínicos y la lista de verificación del protocolo.
    - datos: dict con los campos de CAMPOS_ATENCION que se quieran guardar.
    - pasos_cumplidos: {paso_id: True/False}.
    - finalizar: cierra la atención (completa la hora de fin y marca como no cumplidos los pasos sin responder).
    - exigir_completo: si hay campos obligatorios vacíos, NO finaliza y avisa.
    Devuelve {'estado', 'registro_completo', 'campos_faltantes'}."""
    datos = {k: v for k, v in (datos or {}).items() if k in CAMPOS_ATENCION}
    for k in ("motivo_consulta", "anamnesis", "examen_fisico", "tratamiento", "indicaciones", "observaciones"):
        if k in datos:
            datos[k] = texto(datos[k])
    with transaccion(usuario["id"]) as cur:
        a = uno(cur, "SELECT * FROM atenciones WHERE id = %s", (atencion_id,), "La atención no existe.")
        if a["estado"] == "finalizada":
            raise ErrorValidacion("La atención ya fue finalizada. Use reabrir_atencion() con un motivo.")
        if datos.get("diagnostico_cie10"):
            uno(cur, "SELECT codigo FROM cie10 WHERE codigo = %s", (datos["diagnostico_cie10"],),
                "El diagnóstico CIE-10 no existe.")
        if a["hora_inicio_atencion"] is None and "hora_inicio_atencion" not in datos:
            datos["hora_inicio_atencion"] = ahora()
        if finalizar and a["hora_fin_atencion"] is None and not datos.get("hora_fin_atencion"):
            datos["hora_fin_atencion"] = ahora()
        llegada = datos.get("hora_llegada") or a["hora_llegada"]
        inicio = datos.get("hora_inicio_atencion") or a["hora_inicio_atencion"]
        fin = datos.get("hora_fin_atencion") or a["hora_fin_atencion"]
        if llegada and inicio and inicio < llegada:
            raise ErrorValidacion("La hora de inicio no puede ser anterior a la hora de llegada.")
        if inicio and fin and fin < inicio:
            raise ErrorValidacion("La hora de fin no puede ser anterior a la hora de inicio.")
        if datos:
            sets = ", ".join(f"{c} = %s" for c in datos)
            cur.execute(f"UPDATE atenciones SET {sets} WHERE id = %s", (*datos.values(), atencion_id))
        for paso_id, cumplido in (pasos_cumplidos or {}).items():
            uno(cur, "SELECT id FROM protocolo_pasos WHERE id = %s AND protocolo_id = %s",
                (paso_id, a["protocolo_id"]), f"El paso {paso_id} no pertenece al protocolo de esta atención.")
            cur.execute("""INSERT INTO atencion_protocolo_cumplimiento (atencion_id, paso_id, cumplido)
                           VALUES (%s, %s, %s)
                           ON CONFLICT (atencion_id, paso_id) DO UPDATE SET cumplido = EXCLUDED.cumplido""",
                        (atencion_id, paso_id, bool(cumplido)))
        if finalizar:   # los pasos sin responder cuentan como no cumplidos
            cur.execute("""INSERT INTO atencion_protocolo_cumplimiento (atencion_id, paso_id, cumplido)
                           SELECT %s, id, FALSE FROM protocolo_pasos WHERE protocolo_id = %s
                           ON CONFLICT (atencion_id, paso_id) DO NOTHING""", (atencion_id, a["protocolo_id"]))
        # El trigger de la BD recalcula registro_completo y campos_faltantes
        a = uno(cur, "SELECT estado, registro_completo, campos_faltantes FROM atenciones WHERE id = %s", (atencion_id,))
    resultado = {"estado": a["estado"], "registro_completo": a["registro_completo"],
                 "campos_faltantes": list(a["campos_faltantes"])}
    if finalizar:
        if exigir_completo and not a["registro_completo"]:
            raise ErrorValidacion("No se puede finalizar: faltan campos obligatorios: "
                                  + ", ".join(resultado["campos_faltantes"]))
        with transaccion(usuario["id"]) as cur:
            cur.execute("UPDATE atenciones SET estado = 'finalizada' WHERE id = %s", (atencion_id,))
        resultado["estado"] = "finalizada"
    return resultado
 
 
@requiere("atenciones.registrar")
def reabrir_atencion(usuario, atencion_id, motivo):
    """Reabre una atención finalizada para corregirla. Solo el médico que la registró y con motivo."""
    motivo = exigir(motivo, "motivo de reapertura")
    with transaccion(usuario["id"]) as cur:
        a = uno(cur, "SELECT * FROM atenciones WHERE id = %s", (atencion_id,), "La atención no existe.")
        if a["estado"] != "finalizada":
            raise ErrorValidacion("La atención no está finalizada.")
        if a["medico_id"] != usuario["id"]:
            raise ErrorValidacion("Solo el médico que registró la atención puede reabrirla.")
        cur.execute("UPDATE atenciones SET estado = 'borrador' WHERE id = %s", (atencion_id,))
        registrar_auditoria(cur, usuario, "REABRIR", "atenciones", atencion_id, {"motivo": motivo})
 
 
@requiere("atenciones.ver")
def obtener_atencion(usuario, atencion_id):
    """Atención completa con protocolo, procedimientos, exámenes, eventos y encuesta. Registra VER."""
    with transaccion(usuario["id"]) as cur:
        a = uno(cur, """SELECT a.*, c.descripcion AS diagnostico, p.codigo AS paciente_codigo,
                               p.nombres || ' ' || p.apellidos AS paciente,
                               u.nombres || ' ' || u.apellidos AS medico
                        FROM atenciones a
                        JOIN pacientes p ON p.id = a.paciente_id
                        JOIN usuarios u ON u.id = a.medico_id
                        LEFT JOIN cie10 c ON c.codigo = a.diagnostico_cie10
                        WHERE a.id = %s""", (atencion_id,), "La atención no existe.")
        cur.execute("""SELECT s.id AS paso_id, s.orden, s.descripcion, s.obligatorio, COALESCE(x.cumplido, FALSE) AS cumplido
                       FROM protocolo_pasos s
                       LEFT JOIN atencion_protocolo_cumplimiento x ON x.paso_id = s.id AND x.atencion_id = %s
                       WHERE s.protocolo_id = %s ORDER BY s.orden""", (atencion_id, a["protocolo_id"]))
        a["pasos"] = cur.fetchall()
        for clave, tabla in (("procedimientos", "procedimientos"), ("examenes", "examenes_resultados"),
                             ("eventos_adversos", "eventos_adversos")):
            cur.execute(f"SELECT * FROM {tabla} WHERE atencion_id = %s ORDER BY id", (atencion_id,))
            a[clave] = cur.fetchall()
        cur.execute("SELECT * FROM encuestas_satisfaccion WHERE atencion_id = %s", (atencion_id,))
        a["encuesta"] = cur.fetchone()
        registrar_auditoria(cur, usuario, "VER", "atenciones", atencion_id)
        return a
 
 
@requiere("atenciones.registrar")
def registrar_procedimiento(usuario, atencion_id, tipo, hallazgos=None, conclusion=None, fecha=None):
    tipo = exigir(tipo, "tipo de procedimiento")
    with transaccion(usuario["id"]) as cur:
        a = uno(cur, "SELECT paciente_id, fecha_atencion FROM atenciones WHERE id = %s", (atencion_id,),
                "La atención no existe.")
        cur.execute("""INSERT INTO procedimientos (atencion_id, paciente_id, tipo, fecha, hallazgos, conclusion, realizado_por)
                       VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id""",
                    (atencion_id, a["paciente_id"], tipo, a_fecha(fecha) if fecha else a["fecha_atencion"],
                     texto(hallazgos), texto(conclusion), usuario["id"]))
        return cur.fetchone()["id"]
 
 
@requiere("atenciones.registrar")
def registrar_examen(usuario, atencion_id, tipo, nombre_examen, resultado=None, valor_numerico=None,
                     unidad=None, fecha=None):
    if tipo not in ("laboratorio", "patologia", "imagen", "otro"):
        raise ErrorValidacion("Tipo de examen inválido (laboratorio, patologia, imagen u otro).")
    with transaccion(usuario["id"]) as cur:
        a = uno(cur, "SELECT paciente_id, fecha_atencion FROM atenciones WHERE id = %s", (atencion_id,),
                "La atención no existe.")
        cur.execute("""INSERT INTO examenes_resultados (atencion_id, paciente_id, tipo, nombre_examen, fecha,
                                                        resultado, valor_numerico, unidad)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id""",
                    (atencion_id, a["paciente_id"], tipo, exigir(nombre_examen, "nombre del examen"),
                     a_fecha(fecha) if fecha else a["fecha_atencion"], texto(resultado), valor_numerico, texto(unidad)))
        return cur.fetchone()["id"]
 
 
@requiere("eventos.registrar")
def registrar_evento_adverso(usuario, atencion_id, tipo, gravedad, descripcion, procedimiento_id=None,
                             accion_tomada=None, fecha_evento=None):
    """Registra un evento adverso ligado a una atención (base del indicador de seguridad)."""
    if gravedad not in ("leve", "moderado", "grave", "mortal"):
        raise ErrorValidacion("Gravedad inválida (leve, moderado, grave o mortal).")
    with transaccion(usuario["id"]) as cur:
        a = uno(cur, "SELECT paciente_id, fecha_atencion FROM atenciones WHERE id = %s", (atencion_id,),
                "La atención no existe.")
        if procedimiento_id:
            uno(cur, "SELECT id FROM procedimientos WHERE id = %s AND atencion_id = %s",
                (procedimiento_id, atencion_id), "El procedimiento no pertenece a esta atención.")
        cur.execute("""INSERT INTO eventos_adversos (atencion_id, procedimiento_id, paciente_id, tipo, gravedad,
                                                     descripcion, fecha_evento, accion_tomada, registrado_por)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id""",
                    (atencion_id, procedimiento_id, a["paciente_id"], exigir(tipo, "tipo de evento"), gravedad,
                     exigir(descripcion, "descripción"), a_fecha(fecha_evento) if fecha_evento else a["fecha_atencion"],
                     texto(accion_tomada), usuario["id"]))
        return cur.fetchone()["id"]
 
 
@requiere("citas.gestionar")
def registrar_encuesta(usuario, atencion_id, puntaje, tiempo_espera_aceptable=None, comentario=None):
    if not isinstance(puntaje, int) or not 1 <= puntaje <= 5:
        raise ErrorValidacion("El puntaje debe ser un entero entre 1 y 5.")
    try:
        with transaccion(usuario["id"]) as cur:
            uno(cur, "SELECT id FROM atenciones WHERE id = %s", (atencion_id,), "La atención no existe.")
            cur.execute("""INSERT INTO encuestas_satisfaccion (atencion_id, puntaje, tiempo_espera_aceptable, comentario)
                           VALUES (%s, %s, %s, %s) RETURNING id""",
                        (atencion_id, puntaje, tiempo_espera_aceptable, texto(comentario)))
            return cur.fetchone()["id"]
    except psycopg2.errors.UniqueViolation:
        raise ErrorValidacion("Esta atención ya tiene una encuesta registrada.")
 
 
@requiere("atenciones.ver")
def historial_paciente(usuario, paciente_id):
    """Historial cronológico de atenciones del paciente (más reciente primero). Registra VER."""
    with transaccion(usuario["id"]) as cur:
        uno(cur, "SELECT id FROM pacientes WHERE id = %s", (paciente_id,), "El paciente no existe.")
        cur.execute("""SELECT a.id, a.fecha_atencion, a.estado, a.registro_completo, a.diagnostico_cie10,
                              c.descripcion AS diagnostico, a.motivo_consulta, a.tratamiento,
                              u.nombres || ' ' || u.apellidos AS medico,
                              COALESCE((SELECT json_agg(pr.tipo) FROM procedimientos pr WHERE pr.atencion_id = a.id), '[]'::json) AS procedimientos,
                              (SELECT count(*) FROM eventos_adversos e WHERE e.atencion_id = a.id) AS eventos_adversos
                       FROM atenciones a
                       JOIN usuarios u ON u.id = a.medico_id
                       LEFT JOIN cie10 c ON c.codigo = a.diagnostico_cie10
                       WHERE a.paciente_id = %s ORDER BY a.fecha_atencion DESC, a.id DESC""", (paciente_id,))
        filas = cur.fetchall()
        registrar_auditoria(cur, usuario, "VER", "historial", paciente_id, {"atenciones": len(filas)})
        return filas

