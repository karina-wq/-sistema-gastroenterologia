"""Seguridad: inicio de sesión con bloqueo, contraseñas, usuarios y consulta de bitácora."""
import re
import psycopg2
 
from .base import (transaccion, requiere, registrar_auditoria, ErrorValidacion, NoEncontrado,
                   MAX_INTENTOS, MINUTOS_BLOQUEO, TZ, ahora, a_fecha, texto, exigir, uno)
 
GENERICO = "Usuario o contraseña incorrectos."
 
 
def validar_password(clave):
    if len(clave or "") < 8 or not re.search(r"[A-Za-z]", clave) or not re.search(r"\d", clave):
        raise ErrorValidacion("La contraseña debe tener al menos 8 caracteres, con letras y números.")
 
 
def _log_acceso(cur, usuario_id, email, resultado, motivo, ip, agente):
    cur.execute(
        """INSERT INTO intentos_acceso (usuario_id, email_intentado, resultado, motivo, ip, user_agent)
           VALUES (%s, %s, %s, %s, %s, %s)""",
        (usuario_id, email, resultado, motivo, ip or None, (agente or None) and agente[:300]))
 
 
def autenticar(email, password, ip=None, user_agent=None):
    """Valida credenciales. Devuelve {'ok': bool, 'mensaje': str, 'usuario': dict | None}.
    - Registra TODOS los intentos en intentos_acceso.
    - Tras MAX_INTENTOS fallos seguidos bloquea la cuenta MINUTOS_BLOQUEO minutos."""
    email = (email or "").strip().lower()
    with transaccion() as cur:
        # La comparación de la clave se hace en la BD con crypt() (bcrypt)
        cur.execute(
            """SELECT u.id, u.nombres, u.apellidos, u.email, u.activo, u.intentos_fallidos, u.bloqueado_hasta,
                      u.rol_id, r.nombre AS rol, (u.password_hash = crypt(%s, u.password_hash)) AS clave_ok
               FROM usuarios u JOIN roles r ON r.id = u.rol_id
               WHERE lower(u.email) = %s""", (password or "", email))
        u = cur.fetchone()
 
        if u is None:
            _log_acceso(cur, None, email, "fallido", "Usuario no registrado", ip, user_agent)
            return {"ok": False, "mensaje": GENERICO, "usuario": None}
 
        if not u["activo"]:
            _log_acceso(cur, u["id"], email, "denegado", "Usuario inactivo", ip, user_agent)
            return {"ok": False, "mensaje": "Usuario inactivo. Contacte al administrador.", "usuario": None}
 
        if u["bloqueado_hasta"] and u["bloqueado_hasta"] > ahora():
            hasta = u["bloqueado_hasta"].astimezone(TZ).strftime("%H:%M")
            _log_acceso(cur, u["id"], email, "denegado", "Cuenta bloqueada", ip, user_agent)
            return {"ok": False, "mensaje": f"Cuenta bloqueada hasta las {hasta}.", "usuario": None}
 
        if not u["clave_ok"]:
            intentos = u["intentos_fallidos"] + 1
            if intentos >= MAX_INTENTOS:
                cur.execute("""UPDATE usuarios SET intentos_fallidos = 0,
                               bloqueado_hasta = now() + make_interval(mins => %s) WHERE id = %s""",
                            (MINUTOS_BLOQUEO, u["id"]))
                _log_acceso(cur, u["id"], email, "fallido", "Contraseña incorrecta (cuenta bloqueada)", ip, user_agent)
                return {"ok": False, "usuario": None,
                        "mensaje": f"Demasiados intentos. Cuenta bloqueada {MINUTOS_BLOQUEO} minutos."}
            cur.execute("UPDATE usuarios SET intentos_fallidos = %s WHERE id = %s", (intentos, u["id"]))
            _log_acceso(cur, u["id"], email, "fallido", "Contraseña incorrecta", ip, user_agent)
            return {"ok": False, "usuario": None,
                    "mensaje": f"{GENERICO} Intentos restantes: {MAX_INTENTOS - intentos}."}
 
        # Acceso correcto
        cur.execute("""UPDATE usuarios SET intentos_fallidos = 0, bloqueado_hasta = NULL, ultimo_acceso = now()
                       WHERE id = %s""", (u["id"],))
        _log_acceso(cur, u["id"], email, "exitoso", None, ip, user_agent)
        cur.execute("""SELECT p.codigo FROM rol_permisos rp JOIN permisos p ON p.id = rp.permiso_id
                       WHERE rp.rol_id = %s""", (u["rol_id"],))
        permisos = {f["codigo"] for f in cur.fetchall()}
        usuario = {"id": u["id"], "email": u["email"], "nombres": u["nombres"], "apellidos": u["apellidos"],
                   "nombre_completo": f"{u['nombres']} {u['apellidos']}", "rol": u["rol"],
                   "permisos": permisos, "ip": ip}
        return {"ok": True, "mensaje": f"Bienvenido/a, {u['nombres']}.", "usuario": usuario}
 
 
def cambiar_password(usuario, actual, nueva):
    """Cualquier usuario autenticado puede cambiar su propia clave."""
    validar_password(nueva)
    with transaccion(usuario["id"]) as cur:
        fila = uno(cur, "SELECT (password_hash = crypt(%s, password_hash)) AS ok FROM usuarios WHERE id = %s",
                   (actual or "", usuario["id"]))
        if not fila["ok"]:
            raise ErrorValidacion("La contraseña actual es incorrecta.")
        cur.execute("UPDATE usuarios SET password_hash = crypt(%s, gen_salt('bf', 10)) WHERE id = %s",
                    (nueva, usuario["id"]))
        registrar_auditoria(cur, usuario, "UPDATE", "usuarios", usuario["id"], {"accion": "cambio de contraseña"})
 
 
@requiere("usuarios.administrar")
def crear_usuario(usuario, rol, nombres, apellidos, email, password, colegiatura=None, especialidad=None):
    email = exigir(email, "correo").lower()
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        raise ErrorValidacion("El correo no tiene un formato válido.")
    validar_password(password)
    try:
        with transaccion(usuario["id"]) as cur:
            rol_fila = uno(cur, "SELECT id FROM roles WHERE nombre = %s", (rol,), f"El rol «{rol}» no existe.")
            cur.execute(
                """INSERT INTO usuarios (rol_id, nombres, apellidos, email, password_hash, colegiatura, especialidad)
                   VALUES (%s, %s, %s, %s, crypt(%s, gen_salt('bf', 10)), %s, %s) RETURNING id""",
                (rol_fila["id"], exigir(nombres, "nombres"), exigir(apellidos, "apellidos"), email,
                 password, texto(colegiatura), texto(especialidad)))
            nuevo = cur.fetchone()["id"]
            registrar_auditoria(cur, usuario, "INSERT", "usuarios", nuevo, {"email": email, "rol": rol})
            return nuevo
    except psycopg2.errors.UniqueViolation:
        raise ErrorValidacion("Ya existe un usuario con ese correo.")
 
 
@requiere("usuarios.administrar")
def listar_usuarios(usuario):
    with transaccion() as cur:
        cur.execute("""SELECT u.id, u.nombres, u.apellidos, u.email, r.nombre AS rol, u.activo,
                              u.bloqueado_hasta, u.ultimo_acceso
                       FROM usuarios u JOIN roles r ON r.id = u.rol_id ORDER BY u.id""")
        return cur.fetchall()
 
 
@requiere("usuarios.administrar")
def desbloquear_usuario(usuario, usuario_id):
    with transaccion(usuario["id"]) as cur:
        uno(cur, "SELECT id FROM usuarios WHERE id = %s", (usuario_id,), "El usuario no existe.")
        cur.execute("UPDATE usuarios SET intentos_fallidos = 0, bloqueado_hasta = NULL WHERE id = %s", (usuario_id,))
        registrar_auditoria(cur, usuario, "UPDATE", "usuarios", usuario_id, {"accion": "desbloqueo"})
 
 
@requiere("usuarios.administrar")
def cambiar_estado_usuario(usuario, usuario_id, activo):
    if usuario_id == usuario["id"] and not activo:
        raise ErrorValidacion("No puede desactivar su propia cuenta.")
    with transaccion(usuario["id"]) as cur:
        uno(cur, "SELECT id FROM usuarios WHERE id = %s", (usuario_id,), "El usuario no existe.")
        cur.execute("UPDATE usuarios SET activo = %s WHERE id = %s", (bool(activo), usuario_id))
        registrar_auditoria(cur, usuario, "UPDATE", "usuarios", usuario_id,
                            {"accion": "activar" if activo else "desactivar"})
 
 
def _filtro_fechas(campo, desde, hasta, condiciones, params):
    if desde:
        condiciones.append(f"{campo} >= %s")
        params.append(a_fecha(desde, "desde"))
    if hasta:
        condiciones.append(f"{campo} < %s::date + 1")
        params.append(a_fecha(hasta, "hasta"))
 
 
@requiere("auditoria.ver")
def consultar_bitacora(usuario, desde=None, hasta=None, entidad=None, limite=200):
    cond, params = [], []
    _filtro_fechas("b.created_at", desde, hasta, cond, params)
    if entidad:
        cond.append("b.entidad = %s")
        params.append(entidad)
    donde = ("WHERE " + " AND ".join(cond)) if cond else ""
    with transaccion() as cur:
        cur.execute(f"""SELECT b.id, b.created_at, b.accion, b.entidad, b.entidad_id, b.resultado,
                               COALESCE(u.nombres || ' ' || u.apellidos, 'Sistema') AS usuario, b.ip
                        FROM bitacora_auditoria b LEFT JOIN usuarios u ON u.id = b.usuario_id
                        {donde} ORDER BY b.id DESC LIMIT %s""", (*params, limite))
        return cur.fetchall()
 
 
@requiere("auditoria.ver")
def consultar_accesos(usuario, desde=None, hasta=None, solo_no_exitosos=False, limite=200):
    cond, params = [], []
    _filtro_fechas("created_at", desde, hasta, cond, params)
    if solo_no_exitosos:
        cond.append("resultado <> 'exitoso'")
    donde = ("WHERE " + " AND ".join(cond)) if cond else ""
    with transaccion() as cur:
        cur.execute(f"""SELECT id, created_at, email_intentado, resultado, motivo, ip
                        FROM intentos_acceso {donde} ORDER BY id DESC LIMIT %s""", (*params, limite))
        return cur.fetchall()

