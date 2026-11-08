"""Fuente: capa ArcGIS pública del geovisor "Proyectos 6GW" de UPME (SIMEC · Seguimiento FNCER)."""

SERVICIO = ("https://geo.upme.gov.co/server/rest/services/"
            "Capas_EnergiaElectrica/proyectos_unificados_6gw/FeatureServer")
NOMBRE_CAPA = "proyectos_unificados_6gw"
CAPA_RESPALDO = 23          # id observado el 2026-11-03; se busca por nombre primero
PAGINA = 2000               # maxRecordCount del servidor

# Si falta alguno, la corrida falla: UPME cambió la capa y hay que revisar.
CAMPOS_OBLIGATORIOS = [
    "objectid", "nombre_proyecto", "capacidad_mw", "tipo_tecnologia",
    "estado_proyecto", "tipo_proyecto", "fecha_entrada_operacion",
    "cod_dpto", "departamento", "cod_mpio", "municipio",
]
CAMPOS_OPCIONALES = ["Fuente", "anio_mes_fpo", "fecha_actualizacion"]

# Columnas que definen si un snapshot "cambió" (fecha_actualizacion no cuenta).
COLUMNAS_HUELLA = [
    "clave", "nombre_proyecto", "capacidad_mw", "tipo_tecnologia", "estado_proyecto",
    "tipo_proyecto", "fecha_entrada_operacion", "cod_mpio", "fuente",
]

# Protección: si la capa trae muchos menos registros que el último snapshot,
# se asume una falla de UPME (capa a medio cargar) y no se registran "retiros".
CAIDA_MAXIMA = 0.20

# Proyectos más pequeños que esto se resumen en el reporte en vez de listarse uno a uno.
UMBRAL_MW_TABLA = 1.0
DIAS_CAMBIOS_REPORTE = 30

COLORES_TECNOLOGIA = {
    "SOLAR": "#f2b701", "EOLICA": "#3a86ff", "HIDROELECTRICIDAD": "#06a77d",
    "BIOMASA": "#8d6e63", "GEOTERMIA": "#d62828", "OTRA": "#8e8e93",
}
COLORES_ESTADO = {"EN OPERACIÓN": "#06a77d", "EN PRUEBAS": "#f2b701", "PRUEBAS": "#f2b701"}
