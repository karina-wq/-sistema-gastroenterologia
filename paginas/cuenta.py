"""Mi cuenta: cambio de contraseña (disponible para todos los usuarios)."""
import streamlit as st

from sistema import seguridad
from . import utilidades as u


def mostrar(usuario):
    st.title("Mi cuenta")
    st.write(f"**{usuario['nombre_completo']}** · {usuario['email']} · rol **{usuario['rol']}**")

    st.subheader("Cambiar contraseña")
    st.caption("Mínimo 8 caracteres, con letras y números.")
    with st.form("form_clave", clear_on_submit=True):
        actual = st.text_input("Contraseña actual", type="password")
        nueva = st.text_input("Contraseña nueva", type="password")
        repetir = st.text_input("Repita la contraseña nueva", type="password")
        guardar = st.form_submit_button("Cambiar contraseña", type="primary")
    if guardar:
        if nueva != repetir:
            st.error("Las contraseñas nuevas no coinciden.")
        else:
            ok, _ = u.ejecutar(seguridad.cambiar_password, usuario, actual, nueva)
            if ok:
                st.success("Contraseña cambiada correctamente.")
