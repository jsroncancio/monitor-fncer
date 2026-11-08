"""Descarga paginada de la capa ArcGIS de proyectos FNCER de UPME y normalización."""
import hashlib
import logging
import time
import unicodedata

import pandas as pd
import requests

from config.fuente import (CAMPOS_OBLIGATORIOS, CAMPOS_OPCIONALES, CAPA_RESPALDO,
                           NOMBRE_CAPA, PAGINA, SERVICIO)

log = logging.getLogger(__name__)
_sesion = requests.Session()
_sesion.headers["User-Agent"] = "monitor-fncer/1.0 (python-requests)"


def _get(url, params):
    """GET con reintentos. ArcGIS responde 200 con {"error": ...} cuando falla."""
    for i in range(1, 5):
        try:
            r = _sesion.get(url, params=params, timeout=90)
            r.raise_for_status()
            js = r.json()
            if "error" in js:
                raise RuntimeError(f"ArcGIS: {js['error']}")
            return js
        except Exception as e:  # noqa: BLE001 - se re-lanza en el último intento
            if i == 4:
                raise
            log.warning("Intento %d/4 falló (%s). Reintento en %ds", i, e, 2 ** i)
            time.sleep(2 ** i)


def capa():
    """Id de la capa buscándola por nombre (por si UPME republica el servicio)."""
    try:
        info = _get(SERVICIO, {"f": "json"})
        for c in info.get("layers", []):
            if c.get("name") == NOMBRE_CAPA:
                return c["id"]
        log.warning("No encontré la capa %s en el servicio; uso id %d", NOMBRE_CAPA, CAPA_RESPALDO)
    except Exception as e:  # noqa: BLE001
        log.warning("No pude leer la metadata del servicio (%s); uso id %d", e, CAPA_RESPALDO)
    return CAPA_RESPALDO


def descargar_crudo():
    """Todos los registros (atributos + lon/lat WGS84), paginando de a PAGINA."""
    url = f"{SERVICIO}/{capa()}/query"
    total = _get(url, {"where": "1=1", "returnCountOnly": "true", "f": "json"})["count"]
    filas, offset = [], 0
    while True:
        js = _get(url, {
            "where": "1=1", "outFields": "*", "returnGeometry": "true", "outSR": 4326,
            "orderByFields": "objectid", "resultOffset": offset,
            "resultRecordCount": PAGINA, "f": "json",
        })
        feats = js.get("features", [])
        for f in feats:
            a = dict(f["attributes"])
            g = f.get("geometry") or {}
            a["lon"], a["lat"] = g.get("x"), g.get("y")
            filas.append(a)
        if not feats or not js.get("exceededTransferLimit"):
            break
        offset += len(feats)
    df = pd.DataFrame(filas)
    if len(df) != total:
        raise RuntimeError(f"Descargué {len(df)} registros pero el servidor reporta {total}")
    log.info("Descargados %d registros de %s", len(df), url)
    return df


def _txt(s):
    return s.astype("string").str.strip().str.upper().replace({"": pd.NA})


def _ascii(s):
    return unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().upper().strip()


def _fecha(s):
    """ArcGIS entrega fechas como epoch en ms (campo date) o como texto; acepta ambos."""
    num = pd.to_numeric(s, errors="coerce")
    if num.notna().any() and num.notna().sum() >= s.notna().sum():
        return pd.to_datetime(num, unit="ms", errors="coerce").dt.normalize()
    txt = s.astype("string")
    iso = pd.to_datetime(txt, format="%Y-%m-%d", errors="coerce")
    us = pd.to_datetime(txt, format="%m/%d/%Y", errors="coerce")
    return iso.fillna(us)


def normalizar(crudo):
    faltan = [c for c in CAMPOS_OBLIGATORIOS if c not in crudo.columns]
    if faltan:
        raise RuntimeError(f"La capa ya no trae los campos {faltan}. Columnas: {list(crudo.columns)}")
    for c in CAMPOS_OPCIONALES:
        if c not in crudo.columns:
            log.warning("Campo opcional %s ausente", c)
            crudo[c] = pd.NA

    df = pd.DataFrame({
        "objectid": pd.to_numeric(crudo["objectid"], errors="coerce").astype("Int64"),
        "nombre_proyecto": crudo["nombre_proyecto"].astype("string").str.strip(),
        "capacidad_mw": pd.to_numeric(crudo["capacidad_mw"], errors="coerce").round(4),
        "tipo_tecnologia": crudo["tipo_tecnologia"].map(_ascii).replace({"": "OTRA"}),
        "estado_proyecto": _txt(crudo["estado_proyecto"]),
        "tipo_proyecto": crudo["tipo_proyecto"].astype("string").str.strip(),
        "fecha_entrada_operacion": _fecha(crudo["fecha_entrada_operacion"]),
        "fuente": crudo["Fuente"].astype("string").str.strip(),
        "cod_dpto": crudo["cod_dpto"].astype("string").str.zfill(2),
        "departamento": _txt(crudo["departamento"]),
        "cod_mpio": crudo["cod_mpio"].astype("string").str.zfill(5),
        "municipio": _txt(crudo["municipio"]),
        "anio_mes_fpo": crudo["anio_mes_fpo"].astype("string"),
        "fecha_actualizacion_upme": _fecha(crudo["fecha_actualizacion"]),
        "lon": pd.to_numeric(crudo.get("lon"), errors="coerce"),
        "lat": pd.to_numeric(crudo.get("lat"), errors="coerce"),
    })
    df["clave"] = asignar_claves(df)
    return df.sort_values("clave").reset_index(drop=True)


def asignar_claves(df):
    """
    La capa no trae un id de proyecto estable (objectid puede reasignarse cuando UPME
    recarga la capa). La clave es nombre + municipio + tipo + tecnología; si hay
    homónimos en el mismo municipio se numeran (#2, #3...) por fecha y capacidad.
    """
    base = (df["nombre_proyecto"].map(_ascii) + "|" + df["cod_mpio"].fillna("") + "|"
            + df["tipo_proyecto"].map(_ascii) + "|" + df["tipo_tecnologia"])
    h = base.map(lambda s: hashlib.sha1(s.encode()).hexdigest()[:12])
    orden = df.assign(_h=h).sort_values(["_h", "fecha_entrada_operacion", "capacidad_mw", "objectid"])
    n = orden.groupby("_h").cumcount() + 1
    clave = orden["_h"] + n.map(lambda i: "" if i == 1 else f"#{i}")
    return clave.reindex(df.index)


def descargar():
    return normalizar(descargar_crudo())
