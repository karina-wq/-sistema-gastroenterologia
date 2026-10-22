"""Envío de recordatorios de cita por correo electrónico (Gmail).

Requiere dos Secretos en Streamlit:
    GMAIL_USER         = "su.correo@gmail.com"
    GMAIL_APP_PASSWORD = "xxxx xxxx xxxx xxxx"     (contraseña de aplicación de 16 letras)

La "contraseña de aplicación" NO es la clave normal de Gmail: se crea en
myaccount.google.com → Seguridad → Verificación en dos pasos → Contraseñas de aplicaciones.
"""
import smtplib
import ssl
from email.message import EmailMessage

from . import utilidades as u

ASUNTO = "Recordatorio de control - Gastroenterología, Hospital Nacional Arzobispo Loayza"


def configurado():
    return bool(u.secreto("GMAIL_USER") and u.secreto("GMAIL_APP_PASSWORD"))


def enviar(destino, cuerpo, asunto=ASUNTO):
    """Envía un correo de texto simple. Lanza una excepción si Gmail lo rechaza."""
    usuario = str(u.secreto("GMAIL_USER")).strip()
    clave = str(u.secreto("GMAIL_APP_PASSWORD")).replace(" ", "")   # Gmail la muestra con espacios
    mensaje = EmailMessage()
    mensaje["From"] = f"Gastroenterología HNAL <{usuario}>"
    mensaje["To"] = destino
    mensaje["Subject"] = asunto
    mensaje.set_content(cuerpo)
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ssl.create_default_context(), timeout=20) as servidor:
        servidor.login(usuario, clave)
        servidor.send_message(mensaje)
