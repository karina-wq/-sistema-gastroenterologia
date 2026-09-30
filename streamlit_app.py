# =====================================================================
# ETAPA 4a - APLICACION WEB PARA EL PERSONAL DEL HOSPITAL (Streamlit)
# =====================================================================
#
# QUE ES STREAMLIT (para quien no lo conoce)
#   Es una libreria de Python que convierte un script comun en una
#   pagina web, SIN necesidad de saber HTML, CSS ni JavaScript. Cada
#   vez que llamas a una funcion como st.title(...) o st.dataframe(...),
#   Streamlit dibuja algo en la pantalla del navegador.
#   Este archivo (streamlit_app.py) es TODA la aplicacion en un solo
#   archivo, que se organiza en "paginas" con una barra lateral.
#
# COMO SE EJECUTA (2 formas)
#   A) En tu computadora, para probar:
#      1. Instala Python (si no lo tienes).
#      2. Abre una terminal en la carpeta del archivo y ejecuta:
#         pip install streamlit psycopg2-binary pandas
#         streamlit run streamlit_app.py
#      3. Se abrira solo en tu navegador, normalmente en http://localhost:8501
#
#   B) En internet, para que el hospital la use (Streamlit Community Cloud):
#      1. Sube este archivo a un repositorio de GitHub.
#      2. Entra a share.streamlit.io y conecta ese repositorio.
#      3. En "Secrets" (configuracion del sitio) pega tu cadena de
#         conexion de Neon, con este formato exacto:
#         DATABASE_URL = "postgresql://usuario:clave@...neon.tech/pacientes_db?sslmode=require"
#      4. Streamlit Cloud publica la app con un link publico.
#
# NOTA SOBRE SEGURIDAD
#   La cadena de conexion NUNCA se escribe directamente en este archivo
#   (si lo subes a GitHub, cualquiera la veria). Por eso se lee desde
#   "Secrets" con st.secrets, como se muestra abajo.


# --- 1. IMPORTAR LIBRERIAS -------------------------------------------
import streamlit as st       # el motor que dibuja la pagina web
import pandas as pd          # ordena los resultados de la base de datos en tablas
import psycopg2              # conecta Python con PostgreSQL
import hashlib                # para "ocultar" el DNI antes de guardarlo (ver mas abajo)
from datetime import date


# --- 2. CONFIGURACION DE LA PAGINA -----------------------------------
# Esto define el titulo de la pestaña del navegador y el icono.
# Debe ser la PRIMERA orden de Streamlit en el archivo.
st.set_page_config(
    page_title="Control de Pacientes - Gastroenterologia",
    page_icon="🏥",
    layout="wide"   # "wide" = usa todo el ancho de la pantalla
)


# --- 3. CONEXION A LA BASE DE DATOS -----------------------------------
# @st.cache_resource: le dice a Streamlit "no abras una conexion nueva
# cada vez que el usuario hace clic en algo; abre una sola y reutilizala".
# Sin esto, la app se volveria lenta.
@st.cache_resource
def conectar():
    return psycopg2.connect(st.secrets["DATABASE_URL"])
    # st.secrets lee la cadena de conexion desde la configuracion segura
    # de Streamlit Cloud (o de un archivo .streamlit/secrets.toml en local)

conexion = conectar()


# --- 4. FUNCIONES QUE TRAEN DATOS DESDE POSTGRESQL --------------------
# ttl=300: guarda el resultado en memoria 300 segundos (5 minutos) para
# no volver a consultar la base de datos en cada clic del usuario.

@st.cache_data(ttl=300)
def cargar_indicadores():
    """Trae la vista v_indicadores: TEA, TRI, TCP, TRC, TCC, TPS por medicion."""
    return pd.read_sql("SELECT * FROM v_indicadores ORDER BY medicion", conexion)

@st.cache_data(ttl=300)
def cargar_padron(medicion, diagnostico, estado_control):
    """
    Trae el listado de historias clinicas, con filtros opcionales.
    Los %s son reemplazados de forma segura por psycopg2 (evita que un
    texto raro rompa la consulta: esto se llama "inyeccion SQL").
    """
    consulta = """
        SELECT h.nro_historia, p.codigo_anonimizado, h.diagnostico,
               m.nombre AS medicion, h.fecha_apertura,
               x.datos_incompletos, x.registro_correcto
        FROM historias_clinicas h
        JOIN pacientes p   ON p.id = h.paciente_id
        JOIN mediciones m  ON m.id = h.medicion_id
        LEFT JOIN evaluaciones_historia x ON x.historia_id = h.id
        WHERE (%s = 'Todas' OR m.nombre = %s)
          AND (%s = 'Todos' OR h.diagnostico = %s)
        ORDER BY h.fecha_apertura DESC
    """
    return pd.read_sql(consulta, conexion,
                        params=(medicion, medicion, diagnostico, diagnostico))

@st.cache_data(ttl=300)
def cargar_alertas():
    """Trae las alertas de IA pendientes (riesgo de inasistencia, duplicados, etc.)."""
    return pd.read_sql("""
        SELECT a.tipo, a.puntaje, a.detalle, h.nro_historia, a.generada_en
        FROM alertas_ia a
        JOIN historias_clinicas h ON h.id = a.historia_id
        WHERE a.estado = 'PENDIENTE'
        ORDER BY a.puntaje DESC NULLS LAST
    """, conexion)


# --- 5. BARRA LATERAL: elegir la pagina --------------------------------
# st.sidebar pone estos elementos en el panel izquierdo, no en el centro.
st.sidebar.title("Gastroenterologia")
pagina = st.sidebar.radio(
    "Ir a:",
    ["Dashboard", "Registrar historia", "Padron de pacientes",
     "Alertas del sistema", "Reportes"]
)


# --- 6. PAGINA: REGISTRAR HISTORIA (formulario de carga) -----------------
# Esta es la pagina que usaras en el dia a dia: para cargar tus 225
# historias del PRETEST (transcritas de tus fichas en papel) y para
# registrar cada atencion nueva del POSTEST (hecha ya con el sistema).
if pagina == "Registrar historia":
    st.title("Registrar una historia clinica")

    # --- 6.1 Buscar si el paciente ya existe (por DNI) -------------------
    # st.session_state es la "memoria" de Streamlit entre un clic y otro
    # de la MISMA persona, mientras tiene la pagina abierta. La usamos
    # para recordar el paciente que se encontro, sin perderlo cuando el
    # formulario se vuelve a dibujar.
    st.subheader("1. Identificar al paciente")
    dni_ingresado = st.text_input("DNI del paciente (8 digitos)", max_chars=8)

    if st.button("Buscar paciente"):
        if len(dni_ingresado) != 8 or not dni_ingresado.isdigit():
            st.error("El DNI debe tener exactamente 8 numeros.")
        else:
            # Calculamos la misma "huella" (hash) que se guarda en la
            # base de datos, para buscar sin necesitar el DNI real
            # guardado en ningun lado. hashlib.sha256(...) siempre
            # devuelve el mismo resultado para el mismo texto de entrada,
            # asi que sirve para comparar sin descifrar nada.
            hash_buscado = hashlib.sha256(dni_ingresado.encode()).hexdigest()
            resultado = pd.read_sql(
                "SELECT id, apellidos, nombres FROM pacientes WHERE dni_hash = %(h)s",
                conexion, params={"h": hash_buscado}
            )
            if resultado.empty:
                st.info("No se encontro ese DNI. Se registrara como paciente nuevo.")
                st.session_state["paciente_id"] = None
                st.session_state["dni_hash"] = hash_buscado
            else:
                fila = resultado.iloc[0]
                st.success(f"Paciente encontrado: {fila['nombres']} {fila['apellidos']}")
                st.session_state["paciente_id"] = int(fila["id"])
                st.session_state["dni_hash"] = hash_buscado

    # Si todavia no se ha hecho una busqueda en esta visita a la pagina,
    # no mostramos el resto del formulario (evita guardar datos sueltos).
    if "dni_hash" not in st.session_state:
        st.stop()   # st.stop() corta la ejecucion de la pagina aqui mismo

    es_paciente_nuevo = st.session_state["paciente_id"] is None

    # --- 6.2 Datos del paciente (solo si es nuevo) ------------------------
    datos_paciente = {}
    if es_paciente_nuevo:
        st.subheader("2. Datos del paciente (filiacion)")
        col1, col2 = st.columns(2)
        datos_paciente["apellidos"] = col1.text_input("Apellidos")
        datos_paciente["nombres"] = col2.text_input("Nombres")
        datos_paciente["sexo"] = col1.selectbox("Sexo", ["F", "M"])
        datos_paciente["fecha_nacimiento"] = col2.date_input(
            "Fecha de nacimiento", min_value=date(1900, 1, 1), max_value=date.today()
        )
        datos_paciente["lugar_nacimiento"] = col1.text_input("Lugar de nacimiento")
        datos_paciente["grupo_sanguineo"] = col2.selectbox(
            "Grupo sanguineo", ["", "A", "B", "AB", "O"]
        )
        datos_paciente["factor_rh"] = col1.selectbox("Factor RH", ["", "+", "-"])
        datos_paciente["estado_civil"] = col2.selectbox(
            "Estado civil", ["", "Soltero", "Casado", "Conviviente", "Viudo", "Divorciado"]
        )
        datos_paciente["grado_instruccion"] = col1.text_input("Grado de instruccion")
        datos_paciente["ocupacion"] = col2.text_input("Ocupacion")
        datos_paciente["seguro"] = col1.selectbox(
            "Seguro", ["", "SIS", "ESSALUD", "SOAT", "PARTICULAR", "NINGUNO"]
        )
        datos_paciente["telefono"] = col2.text_input("Telefono")
        datos_paciente["domicilio_actual"] = col1.text_input("Domicilio actual")
        datos_paciente["domicilio_procedencia"] = col2.text_input("Domicilio de procedencia")
    else:
        st.subheader("2. Datos del paciente")
        st.caption("Paciente ya registrado; se usaran sus datos existentes.")

    # --- 6.3 Datos de la historia clinica ---------------------------------
    st.subheader("3. Historia clinica de esta atencion")
    col1, col2 = st.columns(2)
    medicion_elegida = col1.selectbox(
        "Esta historia pertenece a", ["PRETEST", "POSTEST"],
        help="PRETEST: ficha de tu recoleccion manual. POSTEST: atencion hecha con el sistema."
    )
    tipo_atencion = col2.selectbox("Tipo de atencion", ["PRIMERA", "SUBSECUENTE"])
    fecha_apertura = col1.date_input("Fecha de la atencion", value=date.today())
    tiempo_enfermedad = col2.text_input("Tiempo de enfermedad (ej. '3 semanas')")

    motivo_consulta = st.text_area("Motivo de consulta")
    sintomas = st.text_area("Sintomas")
    funciones_biologicas = st.text_input("Funciones biologicas (apetito, sueño, deposiciones...)")
    signos_alarma = st.text_input("Signos de alarma (dejar vacio si no hay)")
    uso_ains = st.checkbox("Usa antiinflamatorios (AINEs)")

    col1, col2 = st.columns(2)
    antecedentes_personales = col1.text_area("Antecedentes personales")
    antecedentes_familiares = col2.text_area("Antecedentes familiares")

    col1, col2 = st.columns(2)
    examen_fisico_general = col1.text_area("Examen fisico general")
    examen_fisico_regional = col2.text_area("Examen fisico regional")

    st.markdown("**Diagnostico**")
    col1, col2, col3 = st.columns(3)
    diagnostico = col1.selectbox(
        "Diagnostico", ["Gastritis", "Dispepsia", "ERGE", "Colon irritable",
                        "Ulcera peptica", "Hepatitis", "Pancreatitis"]
    )
    codigo_cie10 = col2.text_input("Codigo CIE-10", value="K29")
    tipo_diagnostico = col3.selectbox(
        "Tipo", ["P", "D", "R"],
        help="P=Presuntivo, D=Definitivo, R=Repetitivo"
    )

    st.markdown("**Plan de trabajo**")
    examenes_solicitados = st.text_input("Examenes solicitados (dejar vacio si ninguno)")
    interconsultas = st.text_input("Interconsultas (dejar vacio si ninguna)")
    tratamiento = st.text_area("Tratamiento")

    # --- 6.4 Lista de verificacion del protocolo --------------------------
    st.subheader("4. Verificacion del protocolo")
    items = pd.read_sql(
        "SELECT id, codigo, descripcion FROM protocolo_items WHERE activo = TRUE ORDER BY codigo",
        conexion
    )
    cumplidos = {}
    for _, item in items.iterrows():
        cumplidos[item["id"]] = st.checkbox(f"{item['codigo']}: {item['descripcion']}")

    # --- 6.5 Proximo control (opcional) -----------------------------------
    st.subheader("5. Proximo control (opcional)")
    programar_control = st.checkbox("Programar un proximo control")
    fecha_proximo_control = None
    if programar_control:
        fecha_proximo_control = st.date_input("Fecha del proximo control")

    # --- 6.6 Guardar todo --------------------------------------------------
    if st.button("Guardar historia clinica", type="primary"):
        # Validacion minima: estos campos son obligatorios para que la
        # historia cuente como "completa" en el indicador TRI/TRC.
        campos_obligatorios = [motivo_consulta, diagnostico, tratamiento]
        if es_paciente_nuevo:
            campos_obligatorios += [datos_paciente["apellidos"], datos_paciente["nombres"]]
        datos_incompletos = any(not str(c).strip() for c in campos_obligatorios)

        try:
            cursor = conexion.cursor()

            # 1) Paciente: lo creamos solo si es nuevo
            if es_paciente_nuevo:
                codigo_anonimo = "P-" + st.session_state["dni_hash"][:10].upper()
                cursor.execute("""
                    INSERT INTO pacientes (codigo_anonimizado, dni_hash, apellidos, nombres,
                        sexo, fecha_nacimiento, lugar_nacimiento, grupo_sanguineo, factor_rh,
                        estado_civil, grado_instruccion, ocupacion, seguro, telefono,
                        domicilio_actual, domicilio_procedencia)
                    VALUES (%(codigo)s, %(dni_hash)s, %(apellidos)s, %(nombres)s, %(sexo)s,
                        %(fecha_nacimiento)s, %(lugar_nacimiento)s,
                        NULLIF(%(grupo_sanguineo)s, ''), NULLIF(%(factor_rh)s, ''),
                        NULLIF(%(estado_civil)s, ''), %(grado_instruccion)s, %(ocupacion)s,
                        NULLIF(%(seguro)s, ''), %(telefono)s, %(domicilio_actual)s,
                        %(domicilio_procedencia)s)
                    RETURNING id
                """, {"codigo": codigo_anonimo, "dni_hash": st.session_state["dni_hash"],
                      **datos_paciente})
                # NULLIF(valor, '') convierte un texto vacio en NULL: evita
                # que un selectbox dejado en "" choque con el CHECK de la
                # columna (que solo acepta ciertas palabras o vacio).
                paciente_id = cursor.fetchone()[0]
            else:
                paciente_id = st.session_state["paciente_id"]

            # 2) Numero de historia: correlativo por paciente (01, 02, ...)
            cursor.execute(
                "SELECT COUNT(*) FROM historias_clinicas WHERE paciente_id = %s",
                (paciente_id,)
            )
            numero_visita = cursor.fetchone()[0] + 1
            nro_historia = f"{medicion_elegida[:3]}-{paciente_id:06d}-{numero_visita:02d}"

            cursor.execute("""
                INSERT INTO historias_clinicas
                    (paciente_id, medicion_id, nro_historia, fecha_apertura, tipo_atencion,
                     motivo_consulta, tiempo_enfermedad, sintomas, funciones_biologicas,
                     signos_alarma, uso_ains, antecedentes_personales, antecedentes_familiares,
                     examen_fisico_general, examen_fisico_regional, diagnostico, codigo_cie10,
                     tipo_diagnostico, examenes_solicitados, interconsultas, tratamiento)
                VALUES (%(paciente_id)s,
                        (SELECT id FROM mediciones WHERE nombre = %(medicion)s),
                        %(nro_historia)s, %(fecha_apertura)s, %(tipo_atencion)s,
                        %(motivo_consulta)s, %(tiempo_enfermedad)s, %(sintomas)s,
                        %(funciones_biologicas)s, %(signos_alarma)s, %(uso_ains)s,
                        %(antecedentes_personales)s, %(antecedentes_familiares)s,
                        %(examen_fisico_general)s, %(examen_fisico_regional)s,
                        %(diagnostico)s, %(codigo_cie10)s, %(tipo_diagnostico)s,
                        NULLIF(%(examenes_solicitados)s, ''), NULLIF(%(interconsultas)s, ''),
                        %(tratamiento)s)
                RETURNING id
            """, {
                "paciente_id": paciente_id, "medicion": medicion_elegida,
                "nro_historia": nro_historia, "fecha_apertura": fecha_apertura,
                "tipo_atencion": tipo_atencion, "motivo_consulta": motivo_consulta,
                "tiempo_enfermedad": tiempo_enfermedad, "sintomas": sintomas,
                "funciones_biologicas": funciones_biologicas, "signos_alarma": signos_alarma,
                "uso_ains": uso_ains, "antecedentes_personales": antecedentes_personales,
                "antecedentes_familiares": antecedentes_familiares,
                "examen_fisico_general": examen_fisico_general,
                "examen_fisico_regional": examen_fisico_regional,
                "diagnostico": diagnostico, "codigo_cie10": codigo_cie10,
                "tipo_diagnostico": tipo_diagnostico,
                "examenes_solicitados": examenes_solicitados,
                "interconsultas": interconsultas, "tratamiento": tratamiento
            })
            historia_id = cursor.fetchone()[0]

            # 3) Verificacion de cada item del protocolo
            for item_id, esta_cumplido in cumplidos.items():
                cursor.execute("""
                    INSERT INTO verificaciones_protocolo (historia_id, item_id, cumplido)
                    VALUES (%s, %s, %s)
                """, (historia_id, int(item_id), esta_cumplido))

            # 4) Proximo control, si se programo uno
            if programar_control and fecha_proximo_control:
                cursor.execute("""
                    INSERT INTO controles_medicos (historia_id, fecha_programada, estado)
                    VALUES (%s, %s, 'PROGRAMADO')
                """, (historia_id, fecha_proximo_control))

            # 5) Evaluacion de la historia (alimenta TRI, TRC y TPS)
            # seguimiento_actualizado empieza en False: todavia no hay
            # ningun control ATENDIDO para esta historia recien creada.
            origen = "FICHA" if medicion_elegida == "PRETEST" else "SISTEMA"
            cursor.execute("""
                INSERT INTO evaluaciones_historia
                    (historia_id, datos_incompletos, registro_correcto,
                     seguimiento_actualizado, origen)
                VALUES (%s, %s, %s, %s, %s)
            """, (historia_id, datos_incompletos, not datos_incompletos, False, origen))

            conexion.commit()
            st.success(f"Historia clinica guardada correctamente (N° {nro_historia}).")
            if datos_incompletos:
                st.warning(
                    "Se guardo, pero falta algun campo obligatorio "
                    "(motivo de consulta, diagnostico o tratamiento). "
                    "Esto contara como registro incompleto (TRI)."
                )
            # Limpiamos la busqueda para que el proximo registro empiece de cero
            del st.session_state["dni_hash"]
            del st.session_state["paciente_id"]

        except Exception as error:
            conexion.rollback()   # deshace cualquier cambio a medias
            st.error(f"No se pudo guardar: {error}")


# --- 7. PAGINA: DASHBOARD -----------------------------------------------
elif pagina == "Dashboard":
    st.title("Dashboard de gestion asistencial")

    indicadores = cargar_indicadores()

    if indicadores.empty:
        st.warning("Aun no hay datos cargados. Ejecuta primero el script de datos de prueba.")
    else:
        # st.columns(3) crea 3 espacios en la misma fila, uno al lado del otro
        fila1 = st.columns(3)
        fila2 = st.columns(3)

        # Tomamos la fila del POSTEST para mostrar el estado mas reciente.
        # .iloc[0] = "la primera fila que cumple la condicion"
        postest = indicadores[indicadores["medicion"] == "POSTEST"]
        datos = postest.iloc[0] if not postest.empty else indicadores.iloc[0]

        # st.metric dibuja una tarjeta con un numero grande. Es la forma
        # mas clara de mostrar un indicador de un vistazo.
        fila1[0].metric("Tasa de eventos adversos (TEA)", f"{datos['tea']}%")
        fila1[1].metric("Registros incompletos (TRI)",   f"{datos['tri']}%")
        fila1[2].metric("Cumplimiento de protocolo (TCP)", f"{datos['tcp']}%")
        fila2[0].metric("Registros correctos (TRC)",     f"{datos['trc']}%")
        fila2[1].metric("Cumplimiento de controles (TCC)", f"{datos['tcc']}%")
        fila2[2].metric("Seguimiento actualizado (TPS)", f"{datos['tps']}%")

        st.divider()   # una linea horizontal para separar secciones
        st.subheader("Comparacion Pretest (manual) vs Postest (sistema)")

        # Reordenamos la tabla para graficarla: cada indicador como fila,
        # y una columna por cada medicion. Esto se llama "pivotear".
        comparacion = indicadores.set_index("medicion")[
            ["tea", "tri", "tcp", "trc", "tcc", "tps"]
        ].T   # .T = transponer (voltear filas por columnas)
        st.bar_chart(comparacion)   # grafico de barras automatico

        st.caption(
            "Nota: estos valores provienen de la vista v_indicadores, "
            "calculada directamente en PostgreSQL."
        )


# --- 8. PAGINA: PADRON DE PACIENTES Y CONTROLES -------------------------
elif pagina == "Padron de pacientes":
    st.title("Padron de pacientes y controles")

    # st.columns crea filtros lado a lado en vez de uno debajo del otro
    col1, col2 = st.columns(2)
    medicion_elegida = col1.selectbox("Medicion", ["Todas", "PRETEST", "POSTEST"])
    diagnostico_elegido = col2.selectbox(
        "Diagnostico",
        ["Todos", "Gastritis", "Dispepsia", "ERGE", "Colon irritable",
         "Ulcera peptica", "Hepatitis", "Pancreatitis"]
    )

    tabla = cargar_padron(medicion_elegida, diagnostico_elegido, "Todos")
    st.dataframe(tabla, use_container_width=True)   # tabla interactiva
    st.caption(f"{len(tabla)} historias encontradas.")


# --- 9. PAGINA: ALERTAS DEL SISTEMA (lo que genera la IA en Colab) ------
elif pagina == "Alertas del sistema":
    st.title("Alertas generadas por el modulo de IA")
    st.caption(
        "Estas alertas las calcula el notebook de Colab (riesgo de "
        "inasistencia, posibles duplicados y seguimiento vencido) y "
        "quedan guardadas en la tabla alertas_ia."
    )

    alertas = cargar_alertas()
    if alertas.empty:
        st.info("No hay alertas pendientes. Ejecuta el notebook de IA para generarlas.")
    else:
        st.dataframe(alertas, use_container_width=True)


# --- 10. PAGINA: REPORTES (exportar a CSV) --------------------------------
elif pagina == "Reportes":
    st.title("Generacion de reportes hospitalarios")

    indicadores = cargar_indicadores()
    st.dataframe(indicadores, use_container_width=True)

    # to_csv(index=False).encode('utf-8') convierte la tabla en texto CSV
    # (el formato que abre Excel). st.download_button crea el boton de
    # descarga; el navegador hace el resto.
    st.download_button(
        label="Descargar indicadores (CSV)",
        data=indicadores.to_csv(index=False).encode("utf-8"),
        file_name=f"indicadores_{date.today()}.csv",
        mime="text/csv"
    )
