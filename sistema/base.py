"""Núcleo del sistema: conexión a Neon, transacciones, errores, permisos y auditoría."""
import os
import functools
from contextlib import contextmanager
from datetime import datetime, date, timedelta, timezone
 
import psycopg2
from psycopg2.extras import RealDictCursor, Json
 
TZ = timezone(timedelta(hours=-5))   # hora de Perú (UTC-5)
MAX_INTENTOS = 5                     # intentos fallidos antes de bloquear la cuenta
MINUTOS_BLOQUEO = 15                 # duración del bloqueo
 
 
# ----------------------------------------------------------------------
# Errores propios (el mensaje se puede mostrar tal cual al usuario)
# ----------------------------------------------------------------------
class ErrorValidacion(Exception):
    """Datos inválidos o regla de negocio incumplida."""
 
 
class PermisoDenegado(Exception):
    """El usuario no tiene permiso para la operación."""
 
 
class NoEncontrado(Exception):
    """El registro solicitado no existe."""
 
 
# ----------------------------------------------------------------------
# Fecha y hora
# ----------------------------------------------------------------------
def ahora():
    return datetime.now(TZ)
 
 
def hoy():
    return ahora().date()
 
 
def a_fecha(valor, campo="fecha"):
    """Convierte texto 'AAAA-MM-DD', date o datetime en date."""
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    try:
        return date.fromisoformat(str(valor)[:10])
    except ValueError:
        raise ErrorValidacion(f"{campo}: formato de fecha inválido (use AAAA-MM-DD).")
 
 
def texto(valor):
    """Texto limpio o None si está vacío."""
    if valor is None:
        return None
    valor = str(valor).strip()
    return valor or None
 
 
def exigir(valor, campo):
    valor = texto(valor)
    if valor is None:
        raise ErrorValidacion(f"El campo «{campo}» es obligatorio.")
    return valor
 
 
# ----------------------------------------------------------------------
# Conexión y transacciones
# ----------------------------------------------------------------------
def obtener_url():
    """Lee la cadena de conexión de los Secretos de Colab (o de una variable de entorno)."""
    try:
        from google.colab import userdata
        return userdata.get("NEON_URL")
    except ImportError:
        return os.environ["NEON_URL"]
 
 
@contextmanager
def transaccion(usuario_id=None):
    """Abre una transacción. Si hay error hace rollback; si no, commit.
    Con usuario_id, los triggers de auditoría de la BD saben quién hizo el cambio."""
    con = psycopg2.connect(obtener_url(), cursor_factory=RealDictCursor)
    try:
        cur = con.cursor()
        if usuario_id is not None:
            cur.execute("SELECT set_config('app.usuario_id', %s, true)", (str(usuario_id),))
        yield cur
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()
 
 
def consultar(sql, params=None):
    """SELECT simple: devuelve una lista de diccionarios."""
    with transaccion() as cur:
        cur.execute(sql, params)
        return cur.fetchall()
 
 
def uno(cur, sql, params, mensaje="Registro no encontrado."):
    """Ejecuta un SELECT que debe devolver exactamente una fila."""
    cur.execute(sql, params)
    fila = cur.fetchone()
    if fila is None:
        raise NoEncontrado(mensaje)
    return fila
 
 
# ----------------------------------------------------------------------
# Auditoría y permisos
# ----------------------------------------------------------------------
def registrar_auditoria(cur, usuario, accion, entidad, entidad_id=None, detalle=None, resultado="exitoso"):
    """Escribe una fila en la bitácora (quién, qué, cuándo, desde qué IP)."""
    cur.execute(
        """INSERT INTO bitacora_auditoria (usuario_id, accion, entidad, entidad_id, detalle, ip, resultado)
           VALUES (%s, %s, %s, %s, %s, %s, %s)""",
        (usuario["id"] if usuario else None, accion, entidad, entidad_id,
         Json(detalle) if detalle is not None else None,
         (usuario.get("ip") or None) if usuario else None, resultado))
 
 
def tiene_permiso(usuario, permiso):
    return bool(usuario) and permiso in usuario.get("permisos", ())
 
 
def _registrar_denegado(usuario, permiso):
    """Guarda el intento sin permiso (alimenta el indicador de accesos no autorizados)."""
    with transaccion() as cur:
        cur.execute(
            """INSERT INTO intentos_acceso (usuario_id, email_intentado, resultado, motivo, ip)
               VALUES (%s, %s, 'denegado', %s, %s)""",
            (usuario["id"], usuario["email"], f"Acceso sin permiso: {permiso}", usuario.get("ip") or None))
        registrar_auditoria(cur, usuario, "ACCESO", "permiso", None, {"permiso": permiso}, "denegado")
 
 
def requiere(permiso):
    """Decorador: la función solo se ejecuta si el usuario (primer argumento) tiene el permiso."""
    def decorador(funcion):
        @functools.wraps(funcion)
        def envoltura(usuario, *args, **kwargs):
            if not tiene_permiso(usuario, permiso):
                if usuario:
                    _registrar_denegado(usuario, permiso)
                raise PermisoDenegado(f"No tiene permiso para esta operación ({permiso}).")
            return funcion(usuario, *args, **kwargs)
        return envoltura
    return decorador

