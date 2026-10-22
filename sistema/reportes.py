"""Reportes e indicadores de la tesis: cálculo, comparativo pretest/postest y exportación a Excel."""
from datetime import datetime
 
import pandas as pd
 
from .base import transaccion, requiere, registrar_auditoria, ErrorValidacion, TZ, hoy, a_fecha
 
 
def _rango(desde, hasta):
    desde = a_fecha(desde, "desde")
    hasta = a_fecha(hasta, "hasta")
    if hasta < desde:
        raise ErrorValidacion("La fecha final no puede ser anterior a la inicial.")
    return desde, hasta
 
 
def _df(cur, columnas_float=()):
    df = pd.DataFrame(cur.fetchall())
    for c in columnas_float:
        if c in df.columns:
            df[c] = df[c].astype(float)
    return df
 
 
@requiere("reportes.ver")
def indicadores(usuario, desde, hasta):
    """Los 6 indicadores de la Tabla 1 para el rango de fechas (numerador, denominador y %)."""
    desde, hasta = _rango(desde, hasta)
    with transaccion() as cur:
        cur.execute("SELECT * FROM indicadores_periodo(%s, %s)", (desde, hasta))
        return _df(cur, ["porcentaje"])
 
 
@requiere("reportes.ver")
def indicadores_mensuales(usuario):
    """Evolución mes a mes de los 6 indicadores."""
    with transaccion() as cur:
        cur.execute("SELECT mes, dimension, codigo, numerador, denominador, porcentaje FROM v_indicadores_mensuales ORDER BY mes, codigo")
        return _df(cur, ["porcentaje"])
 
 
@requiere("reportes.ver")
def comparativo_pre_post(usuario):
    """Pretest (datos manuales) frente a postest (sistema), con la diferencia en puntos porcentuales."""
    with transaccion() as cur:
        cur.execute("SELECT nombre, tipo, codigo, numerador, denominador, porcentaje FROM v_comparativo_pre_post")
        largo = _df(cur, ["porcentaje"])
    if largo.empty:
        return largo
    ancho = largo.pivot_table(index="codigo", columns="tipo", values="porcentaje", aggfunc="first")
    for col in ("pretest", "postest"):
        if col not in ancho.columns:
            ancho[col] = float("nan")
    ancho = ancho[["pretest", "postest"]]
    ancho["diferencia_pp"] = (ancho["postest"] - ancho["pretest"]).round(2)
    return ancho.reset_index()
 
 
@requiere("reportes.ver")
def registros_incompletos(usuario, desde, hasta):
    """Atenciones finalizadas con campos obligatorios vacíos (para corregirlas)."""
    desde, hasta = _rango(desde, hasta)
    with transaccion() as cur:
        cur.execute("""SELECT a.id AS atencion_id, a.fecha_atencion, p.codigo AS paciente,
                              u.nombres || ' ' || u.apellidos AS medico,
                              array_to_string(a.campos_faltantes, ', ') AS campos_faltantes
                       FROM atenciones a
                       JOIN pacientes p ON p.id = a.paciente_id
                       JOIN usuarios u ON u.id = a.medico_id
                       WHERE a.estado = 'finalizada' AND NOT a.registro_completo
                         AND a.fecha_atencion BETWEEN %s AND %s
                       ORDER BY a.fecha_atencion DESC""", (desde, hasta))
        return _df(cur)
 
 
@requiere("reportes.ver")
def eventos_adversos_detalle(usuario, desde, hasta):
    desde, hasta = _rango(desde, hasta)
    with transaccion() as cur:
        cur.execute("""SELECT e.id, e.fecha_evento, p.codigo AS paciente, e.tipo, e.gravedad, e.descripcion,
                              e.accion_tomada, pr.tipo AS procedimiento
                       FROM eventos_adversos e
                       JOIN pacientes p ON p.id = e.paciente_id
                       LEFT JOIN procedimientos pr ON pr.id = e.procedimiento_id
                       WHERE e.fecha_evento BETWEEN %s AND %s ORDER BY e.fecha_evento DESC""", (desde, hasta))
        return _df(cur)
 
 
@requiere("reportes.ver")
def tiempos_atencion(usuario, desde, hasta):
    """Promedio y mediana (minutos) de espera y duración de la atención."""
    desde, hasta = _rango(desde, hasta)
    with transaccion() as cur:
        cur.execute("""SELECT count(*) AS atenciones,
                              round(avg(espera_min)::numeric, 1)::float AS espera_promedio_min,
                              round((percentile_cont(0.5) WITHIN GROUP (ORDER BY espera_min))::numeric, 1)::float AS espera_mediana_min,
                              round(avg(duracion_min)::numeric, 1)::float AS duracion_promedio_min
                       FROM v_atenciones_tiempos WHERE fecha_atencion BETWEEN %s AND %s""", (desde, hasta))
        return _df(cur)
 
 
@requiere("reportes.ver")
def satisfaccion(usuario, desde, hasta):
    desde, hasta = _rango(desde, hasta)
    with transaccion() as cur:
        cur.execute("""SELECT count(*) AS encuestas,
                              round(avg(e.puntaje)::numeric, 2)::float AS puntaje_promedio,
                              round(100.0 * count(*) FILTER (WHERE e.tiempo_espera_aceptable) / NULLIF(count(*), 0), 1)::float
                                  AS pct_espera_aceptable
                       FROM encuestas_satisfaccion e JOIN atenciones a ON a.id = e.atencion_id
                       WHERE a.fecha_atencion BETWEEN %s AND %s""", (desde, hasta))
        return _df(cur)
 
 
@requiere("reportes.ver")
def citas_por_estado(usuario, desde, hasta):
    desde, hasta = _rango(desde, hasta)
    with transaccion() as cur:
        cur.execute("""SELECT estado, count(*) AS citas FROM citas_control
                       WHERE fecha_programada BETWEEN %s AND %s GROUP BY estado ORDER BY citas DESC""", (desde, hasta))
        return _df(cur)
 
 
def _sin_zona(df):
    """Excel no admite fechas con zona horaria: se convierten a hora de Perú sin zona."""
    df = df.copy()
    for c in df.columns:
        s = df[c]
        if isinstance(s.dtype, pd.DatetimeTZDtype):
            df[c] = s.dt.tz_convert("America/Lima").dt.tz_localize(None)
        elif s.dtype == object and s.map(lambda v: isinstance(v, datetime) and v.tzinfo is not None).any():
            df[c] = s.map(lambda v: v.astimezone(TZ).replace(tzinfo=None) if isinstance(v, datetime) and v.tzinfo else v)
    return df
 
 
@requiere("reportes.ver")
def exportar_excel(usuario, desde, hasta, ruta):
    """Genera un Excel con todos los reportes del periodo y deja constancia en la bitácora."""
    desde, hasta = _rango(desde, hasta)
    hojas = {
        "Indicadores": indicadores(usuario, desde, hasta),
        "Mensual": indicadores_mensuales(usuario),
        "Pretest vs Postest": comparativo_pre_post(usuario),
        "Citas por estado": citas_por_estado(usuario, desde, hasta),
        "Tiempos": tiempos_atencion(usuario, desde, hasta),
        "Satisfaccion": satisfaccion(usuario, desde, hasta),
        "Incompletos": registros_incompletos(usuario, desde, hasta),
        "Eventos adversos": eventos_adversos_detalle(usuario, desde, hasta),
    }
    with pd.ExcelWriter(ruta, engine="openpyxl") as escritor:
        for nombre, df in hojas.items():
            df = _sin_zona(df) if not df.empty else pd.DataFrame({"Sin datos": []})
            df.to_excel(escritor, sheet_name=nombre, index=False)
            ws = escritor.sheets[nombre]
            for col in ws.columns:   # ancho de columna según el contenido
                largo = max(len(str(c.value)) if c.value is not None else 0 for c in col)
                ws.column_dimensions[col[0].column_letter].width = min(60, max(12, largo + 2))
    with transaccion(usuario["id"]) as cur:
        registrar_auditoria(cur, usuario, "EXPORTAR", "reportes", None,
                            {"desde": str(desde), "hasta": str(hasta), "archivo": ruta})
    return ruta

