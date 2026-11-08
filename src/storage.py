"""
Almacenamiento en Parquet:
  data/snapshots/fecha=YYYY-MM-DD.parquet  capa completa, solo cuando algo cambió
  data/cambios/anio=YYYY.parquet            eventos por proyecto (nuevo, retirado, estado, MW)
  data/resumen_diario.parquet               MW y conteo por día, tipo, tecnología y estado
"""
import hashlib
from pathlib import Path

import duckdb
import pandas as pd

from config.fuente import COLUMNAS_HUELLA

RAIZ = Path(__file__).resolve().parent.parent
DATA = RAIZ / "data"


def _snap_dir():
    return DATA / "snapshots"


def huella(df):
    cols = df[COLUMNAS_HUELLA].sort_values("clave").astype("string").fillna("<NA>")
    return hashlib.sha256(pd.util.hash_pandas_object(cols, index=False).values.tobytes()).hexdigest()


def snapshots():
    return sorted(_snap_dir().glob("fecha=*.parquet"))


def ultimo_snapshot(antes_de=None):
    """(fecha, df) del último snapshot guardado (estrictamente antes de `antes_de` si se da)."""
    for ruta in reversed(snapshots()):
        fecha = pd.Timestamp(ruta.stem.split("=")[1])
        if antes_de is None or fecha < pd.Timestamp(antes_de):
            return fecha, pd.read_parquet(ruta)
    return None, None


def guardar_snapshot(df, fecha):
    ruta = _snap_dir() / f"fecha={pd.Timestamp(fecha).date().isoformat()}.parquet"
    ruta.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(ruta, index=False)
    return ruta


def _upsert(ruta, nuevo, llaves):
    ruta.parent.mkdir(parents=True, exist_ok=True)
    if ruta.exists():
        nuevo = pd.concat([pd.read_parquet(ruta), nuevo], ignore_index=True)
    nuevo = nuevo.drop_duplicates(llaves, keep="last").sort_values(llaves)
    nuevo.to_parquet(ruta, index=False)


def guardar_cambios(cambios):
    if cambios.empty:
        return
    for anio, parte in cambios.groupby(pd.to_datetime(cambios["fecha"]).dt.year):
        _upsert(DATA / "cambios" / f"anio={anio}.parquet", parte, ["fecha", "clave", "tipo_cambio"])


def guardar_resumen(resumen):
    _upsert(DATA / "resumen_diario.parquet", resumen,
            ["fecha", "tipo_proyecto", "tipo_tecnologia", "estado_proyecto"])


def consulta(sql):
    """SQL con DuckDB. Vistas: resumen_diario, cambios, proyectos (último snapshot)."""
    con = duckdb.connect()
    if (DATA / "resumen_diario.parquet").exists():
        con.execute(f"CREATE VIEW resumen_diario AS SELECT * FROM "
                    f"read_parquet('{(DATA / 'resumen_diario.parquet').as_posix()}')")
    if list((DATA / "cambios").glob("anio=*.parquet")):
        con.execute(f"CREATE VIEW cambios AS SELECT * FROM read_parquet("
                    f"'{(DATA / 'cambios' / 'anio=*.parquet').as_posix()}', union_by_name=true)")
    if snapshots():
        con.execute(f"CREATE VIEW proyectos AS SELECT * FROM read_parquet('{snapshots()[-1].as_posix()}')")
    return con.execute(sql).df()
