"""Paquete del sistema de control de pacientes (lógica de negocio)."""
from . import base, seguridad, clinico, reportes
from .base import ErrorValidacion, PermisoDenegado, NoEncontrado

