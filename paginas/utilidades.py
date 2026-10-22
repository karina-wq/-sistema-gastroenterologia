"""Utilidades compartidas por todas las pantallas de la aplicación.

Aquí vive lo que se repite en varias pantallas:
  - conectar la app con Neon usando los "Secretos" de Streamlit,
  - ejecutar funciones del paquete `sistema` y mostrar sus errores en español,
  - guardar en memoria lo que ya se leyó (para no llenar la bitácora de auditoría),
  - dar formato a fechas, horas y tablas,
  - controlar la sesión (quién entró y cuánto tiempo lleva inactivo).
"""
import ipaddress
import os
import time
from datetime import datetime

import pandas as pd
import psycopg2
import streamlit as st

from sistema import base
from sistema.base import ErrorValidacion, NoEncontrado, PermisoDenegado

SESION_MINUTOS = 30   # tras este tiempo sin actividad, se cierra la sesión


# ----------------------------------------------------------------------
# 1. Conexión con Neon
# ----------------------------------------------------------------------
def secreto(nombre, defecto=None):
    """Lee un valor de los Secretos de Streamlit (o devuelve `defecto` si no existe)."""
    try:
        return st.secrets.get(nombre, defecto)
    except Exception:   # no hay archivo de secretos
        return defecto


def preparar_secretos():
    """Copia la cadena de conexión de los Secretos a la variable NEON_URL, que es la
    que lee el paquete `sistema` (base.obtener_url). Devuelve True si todo está listo."""
    if os.environ.get("NEON_URL"):
        return True
    url = secreto("NEON_URL") or secreto("DATABASE_URL")   # DATABASE_URL: nombre usado en la versión anterior
    if not url:
        return False
    os.environ["NEON_URL"] = url
    os.environ.setdefault("PGCONNECT_TIMEOUT", "20")   # evita esperas infinitas si Neon está dormida
    return True


# ----------------------------------------------------------------------
# 2. Ejecutar funciones del paquete y mostrar errores
# ----------------------------------------------------------------------
def ejecutar(funcion, *args, **kwargs):
    """Ejecuta una función del paquete `sistema`.
    Devuelve (True, resultado) si salió bien, o (False, None) si hubo un error;
    en ese caso el mensaje ya se mostró en pantalla."""
    try:
        return True, funcion(*args, **kwargs)
    except (ErrorValidacion, NoEncontrado, PermisoDenegado) as e:
        st.error(str(e))
    except (psycopg2.OperationalError, psycopg2.InterfaceError):
        st.error("No se pudo conectar con la base de datos. Espere unos segundos y vuelva a intentar "
                 "(si estaba inactiva, tarda un momento en despertar).")
    except Exception as e:   # error inesperado: no se muestran detalles técnicos al personal
        st.error("Ocurrió un error inesperado. Avise al administrador del sistema.")
        if secreto("DEPURAR", False):   # solo si el administrador activó DEPURAR = true en los Secretos
            st.exception(e)
    return False, None


# ----------------------------------------------------------------------
# 3. Memoria de lecturas (evita registrar "VER" en la bitácora en cada clic)
# ----------------------------------------------------------------------
def leer_cache(clave, funcion, *args, forzar=False, **kwargs):
    """Lee una vez y guarda el resultado en la sesión. Las funciones que abren fichas o
    atenciones dejan una fila en la bitácora cada vez que se llaman; con esta memoria
    solo se registra la primera lectura (o cuando se pide actualizar)."""
    if forzar or clave not in st.session_state:
        ok, valor = ejecutar(funcion, *args, **kwargs)
        if not ok:
            return None
        st.session_state[clave] = valor
    return st.session_state[clave]


def invalidar(*prefijos):
    """Borra de la memoria lo que empiece con alguno de los prefijos (tras guardar cambios)."""
    for k in [k for k in st.session_state if any(str(k).startswith(p) for p in prefijos)]:
        del st.session_state[k]


# ----------------------------------------------------------------------
# 4. Avisos y navegación entre pantallas
# ----------------------------------------------------------------------
def avisar(mensaje, tipo="success"):
    """Guarda un aviso para mostrarlo después del próximo rerun (st.rerun borra lo escrito antes)."""
    st.session_state.setdefault("_avisos", []).append((tipo, mensaje))


def mostrar_avisos():
    for tipo, mensaje in st.session_state.pop("_avisos", []):
        {"success": st.success, "warning": st.warning, "error": st.error, "info": st.info}[tipo](mensaje)


def ir_a_pagina(nombre, **estado):
    """Cambia de pantalla. `estado` deja valores listos para la pantalla de destino."""
    st.session_state["_ir_pagina"] = nombre
    st.session_state.update({f"_destino_{k}": v for k, v in estado.items()})
    st.rerun()


# ----------------------------------------------------------------------
# 5. Sesión
# ----------------------------------------------------------------------
def tiene(usuario, permiso):
    return base.tiene_permiso(usuario, permiso)


def cerrar_sesion(motivo=None):
    for k in list(st.session_state.keys()):
        del st.session_state[k]
    if motivo:
        st.session_state["_avisos"] = [("info", motivo)]
    st.rerun()


def controlar_inactividad():
    """Cierra la sesión si pasaron SESION_MINUTOS sin usar la aplicación."""
    ahora = time.time()
    ultima = st.session_state.get("_ultima_actividad", ahora)
    if ahora - ultima > SESION_MINUTOS * 60:
        cerrar_sesion(f"La sesión se cerró por inactividad ({SESION_MINUTOS} minutos).")
    st.session_state["_ultima_actividad"] = ahora


def ip_y_agente():
    """IP y navegador de quien inicia sesión (para la bitácora de accesos). Si no se
    pueden obtener, devuelve None; nunca rompe el inicio de sesión."""
    try:
        cabeceras = st.context.headers
        ip = (cabeceras.get("X-Forwarded-For") or "").split(",")[0].strip()
        ipaddress.ip_address(ip)   # valida el formato (la columna es de tipo inet)
        agente = cabeceras.get("User-Agent")
        return ip, agente
    except Exception:
        try:
            return None, st.context.headers.get("User-Agent")
        except Exception:
            return None, None


# ----------------------------------------------------------------------
# 6. Catálogos pequeños (se guardan 5 minutos para todos los usuarios)
# ----------------------------------------------------------------------
@st.cache_data(ttl=300, show_spinner=False)
def medicos_activos():
    """{id: 'Nombre Apellido'} de los usuarios con rol médico que están activos."""
    filas = base.consultar("""SELECT u.id, u.nombres || ' ' || u.apellidos AS nombre
                              FROM usuarios u JOIN roles r ON r.id = u.rol_id
                              WHERE r.nombre = 'medico' AND u.activo ORDER BY u.apellidos, u.nombres""")
    return {f["id"]: f["nombre"] for f in filas}


@st.cache_data(ttl=300, show_spinner=False)
def diagnosticos():
    """{código CIE-10: 'K29.7 · descripción'} para los selectores."""
    filas = base.consultar("SELECT codigo, descripcion FROM cie10 ORDER BY codigo")
    return {f["codigo"]: f"{f['codigo']} · {f['descripcion']}" for f in filas}


@st.cache_data(ttl=300, show_spinner=False)
def roles_disponibles():
    return [f["nombre"] for f in base.consultar("SELECT nombre FROM roles ORDER BY id")]


@st.cache_data(ttl=120, show_spinner=False)
def hay_datos_simulados():
    """True si la base todavía tiene pacientes de prueba (código SIM-...)."""
    try:
        return base.consultar("SELECT count(*) AS n FROM pacientes WHERE codigo LIKE 'SIM-%'")[0]["n"] > 0
    except Exception:
        return False


# ----------------------------------------------------------------------
# 7. Formato
# ----------------------------------------------------------------------
def fecha_txt(valor):
    return valor.strftime("%d/%m/%Y") if valor else "—"


def hora_txt(valor):
    """Hora de Perú (HH:MM) de un datetime con zona horaria o de un time."""
    if not valor:
        return "—"
    if isinstance(valor, datetime) and valor.tzinfo:
        valor = valor.astimezone(base.TZ)
    return valor.strftime("%H:%M")


def a_df(filas, columnas=None, nombres=None):
    """Convierte las filas de la base en una tabla lista para mostrar:
    horas en hora de Perú, columnas en el orden pedido y con nombres legibles."""
    df = pd.DataFrame(filas)
    if df.empty:
        return df
    for c in df.columns:
        s = df[c]
        if isinstance(s.dtype, pd.DatetimeTZDtype):
            df[c] = s.dt.tz_convert("America/Lima").dt.tz_localize(None)
        elif s.dtype == object:
            if s.map(lambda v: isinstance(v, datetime) and v.tzinfo is not None).any():
                df[c] = s.map(lambda v: v.astimezone(base.TZ).replace(tzinfo=None)
                              if isinstance(v, datetime) and v.tzinfo else v)
            elif s.map(lambda v: hasattr(v, "hour") and not hasattr(v, "year")).any():   # objetos time
                df[c] = s.map(lambda v: v.strftime("%H:%M") if hasattr(v, "strftime") else v)
    if columnas:
        df = df[[c for c in columnas if c in df.columns]]
    if nombres:
        df = df.rename(columns=nombres)
    return df


def csv_bytes(df):
    """CSV con codificación que Excel abre bien (UTF-8 con marca BOM)."""
    return df.to_csv(index=False).encode("utf-8-sig")
