"""
Monitor de instalación FNCER: descarga la capa de proyectos de UPME, guarda un
snapshot en Parquet si algo cambió, registra los cambios por proyecto y regenera
el reporte en docs/.

    python main.py
    python main.py --sin-reporte
    python main.py --forzar        # registra aunque la capa venga con muchos menos registros
"""
import argparse
import datetime as dt
import logging
import sys
from zoneinfo import ZoneInfo

from config.fuente import CAIDA_MAXIMA
from src import cambios, extractor, reporte, storage

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("main")


def actualizar(fecha, forzar=False, df=None):
    df = extractor.descargar() if df is None else df
    fecha_prev, prev = storage.ultimo_snapshot(antes_de=fecha + dt.timedelta(days=1))
    if prev is not None and fecha_prev.date() == fecha:
        # Segunda corrida del mismo día: comparar contra el snapshot anterior a hoy.
        fecha_prev, prev = storage.ultimo_snapshot(antes_de=fecha)

    if prev is not None and len(df) < (1 - CAIDA_MAXIMA) * len(prev) and not forzar:
        raise RuntimeError(
            f"La capa trae {len(df)} registros vs {len(prev)} del {fecha_prev.date()} "
            f"(caída > {CAIDA_MAXIMA:.0%}). Probable falla de UPME; no registro nada. "
            "Usa --forzar si el cambio es real.")

    storage.guardar_resumen(cambios.resumen(df, fecha))

    if prev is not None and storage.huella(prev) == storage.huella(df):
        log.info("Sin cambios frente al snapshot del %s", fecha_prev.date())
        return 0
    ruta = storage.guardar_snapshot(df, fecha)
    log.info("Snapshot guardado: %s (%d proyectos, %.1f MW)", ruta.name, len(df), df["capacidad_mw"].sum())
    if prev is None:
        log.info("Primer snapshot: los cambios se registran desde la próxima corrida")
        return 0
    ev = cambios.comparar(prev, df, fecha)
    storage.guardar_cambios(ev)
    for tipo, n in ev["tipo_cambio"].value_counts().items():
        log.info("  %s: %d", tipo, n)
    return len(ev)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--sin-reporte", action="store_true")
    p.add_argument("--forzar", action="store_true")
    a = p.parse_args()

    storage.DATA.mkdir(exist_ok=True)
    hoy = dt.datetime.now(ZoneInfo("America/Bogota")).date()
    codigo = 0
    try:
        actualizar(hoy, a.forzar)
    except Exception:
        log.exception("Falló la actualización desde UPME")
        codigo = 1  # el workflow queda en rojo y GitHub avisa por correo
        if not storage.snapshots():
            return codigo
    if not a.sin_reporte:
        log.info("Reporte: %s", reporte.generar())
    return codigo


if __name__ == "__main__":
    sys.exit(main())
