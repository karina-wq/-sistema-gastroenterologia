"""Administración: usuarios, bitácora de auditoría y accesos al sistema."""
from datetime import timedelta

import streamlit as st

from sistema import base, seguridad
from sistema.base import hoy
from . import utilidades as u


def mostrar(usuario):
    st.title("Administración")
    secciones = []
    if u.tiene(usuario, "usuarios.administrar"):
        secciones.append("Usuarios")
    if u.tiene(usuario, "auditoria.ver"):
        secciones += ["Bitácora de auditoría", "Accesos al sistema"]
    seccion = st.radio("Sección", secciones, horizontal=True, label_visibility="collapsed", key="adm_seccion")
    {"Usuarios": usuarios, "Bitácora de auditoría": bitacora, "Accesos al sistema": accesos}[seccion](usuario)


# ----------------------------------------------------------------------
def usuarios(usuario):
    ok, filas = u.ejecutar(seguridad.listar_usuarios, usuario)
    if not ok:
        return
    st.dataframe(u.a_df(filas, ["id", "nombres", "apellidos", "email", "rol", "activo", "bloqueado_hasta", "ultimo_acceso"],
                        {"id": "N.º", "nombres": "Nombres", "apellidos": "Apellidos", "email": "Correo", "rol": "Rol",
                         "activo": "Activo", "bloqueado_hasta": "Bloqueado hasta", "ultimo_acceso": "Último acceso"}),
                 hide_index=True, width="stretch")

    st.markdown("##### Administrar una cuenta")
    por_id = {f["id"]: f for f in filas}
    elegido = st.selectbox("Usuario", list(por_id), index=None, placeholder="Elija un usuario", key="adm_usuario",
                           format_func=lambda i: f"{por_id[i]['nombres']} {por_id[i]['apellidos']} · {por_id[i]['email']}"
                                                 f" · {por_id[i]['rol']}")
    if elegido:
        f = por_id[elegido]
        a, b = st.columns(2)
        if a.button("🔓 Desbloquear cuenta", key=f"adm_desb_{elegido}"):
            ok, _ = u.ejecutar(seguridad.desbloquear_usuario, usuario, elegido)
            if ok:
                u.avisar("Cuenta desbloqueada.")
                st.rerun()
        etiqueta = "⏸ Desactivar usuario" if f["activo"] else "▶ Activar usuario"
        if b.button(etiqueta, key=f"adm_act_{elegido}"):
            ok, _ = u.ejecutar(seguridad.cambiar_estado_usuario, usuario, elegido, not f["activo"])
            if ok:
                u.avisar("Usuario desactivado." if f["activo"] else "Usuario activado.")
                u.medicos_activos.clear()
                st.rerun()

    with st.expander("Crear usuario nuevo"):
        with st.form("form_usuario", clear_on_submit=True):
            c1, c2 = st.columns(2)
            rol = c1.selectbox("Rol", u.roles_disponibles())
            email = c2.text_input("Correo")
            nombres = c1.text_input("Nombres")
            apellidos = c2.text_input("Apellidos")
            colegiatura = c1.text_input("N.º de colegiatura (médicos)")
            especialidad = c2.text_input("Especialidad")
            clave = c1.text_input("Contraseña inicial", type="password", help="Mínimo 8 caracteres, con letras y números.")
            repetir = c2.text_input("Repita la contraseña", type="password")
            crear = st.form_submit_button("Crear usuario", type="primary")
        if crear:
            if clave != repetir:
                st.error("Las contraseñas no coinciden.")
            else:
                ok, _ = u.ejecutar(seguridad.crear_usuario, usuario, rol, nombres, apellidos, email, clave,
                                   colegiatura, especialidad)
                if ok:
                    u.medicos_activos.clear()
                    u.avisar("Usuario creado. Pídale que cambie su contraseña en «Mi cuenta».")
                    st.rerun()


# ----------------------------------------------------------------------
def filtros_fecha(clave):
    c1, c2, c3 = st.columns(3)
    desde = c1.date_input("Desde", hoy() - timedelta(days=7), key=f"{clave}_desde", format="DD/MM/YYYY")
    hasta = c2.date_input("Hasta", hoy(), key=f"{clave}_hasta", format="DD/MM/YYYY")
    limite = c3.selectbox("Máximo de filas", [200, 500, 1000], key=f"{clave}_limite")
    return desde, hasta, limite


def bitacora(usuario):
    st.caption("Quién hizo qué y cuándo. Incluye las lecturas de datos clínicos.")
    desde, hasta, limite = filtros_fecha("bit")
    entidades = [f["entidad"] for f in base.consultar(
        "SELECT DISTINCT entidad FROM bitacora_auditoria WHERE entidad IS NOT NULL ORDER BY 1")]
    entidad = st.selectbox("Entidad", [None] + entidades, format_func=lambda e: "Todas" if e is None else e, key="bit_entidad")
    ok, filas = u.ejecutar(seguridad.consultar_bitacora, usuario, desde, hasta, entidad, limite)
    if not ok:
        return
    if not filas:
        st.info("No hay registros en ese rango.")
        return
    df = u.a_df(filas, ["created_at", "usuario", "accion", "entidad", "entidad_id", "resultado", "ip"],
                {"created_at": "Fecha y hora", "usuario": "Usuario", "accion": "Acción", "entidad": "Entidad",
                 "entidad_id": "N.º registro", "resultado": "Resultado", "ip": "IP"})
    st.dataframe(df, hide_index=True, width="stretch")
    st.download_button("Descargar (CSV)", u.csv_bytes(df), "bitacora_auditoria.csv", "text/csv")


def accesos(usuario):
    st.caption("Todos los intentos de inicio de sesión y los accesos denegados.")
    desde, hasta, limite = filtros_fecha("acc")
    solo_fallidos = st.checkbox("Mostrar solo los no exitosos", value=True, key="acc_solo")
    ok, filas = u.ejecutar(seguridad.consultar_accesos, usuario, desde, hasta, solo_fallidos, limite)
    if not ok:
        return
    if not filas:
        st.info("No hay registros en ese rango.")
        return
    df = u.a_df(filas, ["created_at", "email_intentado", "resultado", "motivo", "ip"],
                {"created_at": "Fecha y hora", "email_intentado": "Correo", "resultado": "Resultado",
                 "motivo": "Motivo", "ip": "IP"})
    st.dataframe(df, hide_index=True, width="stretch")
    st.download_button("Descargar (CSV)", u.csv_bytes(df), "accesos.csv", "text/csv")
