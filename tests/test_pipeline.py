"""
Prueba de punta a punta sin red: simula el FeatureServer de ArcGIS (paginación,
exceededTransferLimit, fechas epoch) y recorre tres días de corridas.

    python -m pytest tests/        (o)    python tests/test_pipeline.py
"""
import datetime as dt
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd  # noqa: E402
import pytest  # noqa: E402

import main  # noqa: E402
from src import extractor, reporte, storage  # noqa: E402


def _ms(s):
    return int(pd.Timestamp(s).timestamp() * 1000)


def _proyecto(oid, nombre, mw, tec, estado, tipo, fpo, mpio="08560", dpto="ATLÁNTICO", muni="PONEDERA"):
    return {"objectid": oid, "nombre_proyecto": nombre, "capacidad_mw": mw, "tipo_tecnologia": tec,
            "estado_proyecto": estado, "tipo_proyecto": tipo, "fecha_entrada_operacion": _ms(fpo),
            "Fuente": "XM API", "cod_dpto": mpio[:2], "departamento": dpto, "cod_mpio": mpio,
            "municipio": muni, "anio_mes_fpo": fpo[:7], "fecha_actualizacion": "10/30/2026"}


def base():
    filas = [
        _proyecto(1, "GUAYEPO", 388, "SOLAR", "EN OPERACIÓN", "Generacion Centralizada", "2024-11-30"),
        _proyecto(2, "PARQUE SOLAR PUERTA DE ORO", 300, "SOLAR", "EN OPERACIÓN",
                  "Generacion Centralizada", "2026-07-04", "25320", "CUNDINAMARCA", "GUADUAS"),
        _proyecto(3, "GUAYEPO III", 200, "SOLAR", "EN PRUEBAS", "Generacion Centralizada", "2026-02-25"),
        _proyecto(4, "EOLICO X", 41, "EÓLICA", "EN PRUEBAS", "Generacion Centralizada",
                  "2026-09-01", "44847", "LA GUAJIRA", "URIBIA"),
    ]
    # Muchas instalaciones pequeñas, con homónimos en el mismo municipio (AGPE)
    for i in range(5000):
        filas.append(_proyecto(100 + i, f"AGPE {i % 2400}", 0.01 * (i % 50 + 1), "SOLAR", "EN OPERACIÓN",
                               "Autogeneracion Pequeña Escala", "2025-01-01", "05001", "ANTIOQUIA", "MEDELLÍN"))
    return filas


class FakeServidor:
    def __init__(self, filas):
        self.filas = filas
        self.llamadas = 0

    def __call__(self, url, params):
        self.llamadas += 1
        if url.endswith("FeatureServer"):
            return {"layers": [{"id": 23, "name": "proyectos_unificados_6gw"}]}
        assert url.endswith("/23/query")
        if params.get("returnCountOnly") == "true":
            return {"count": len(self.filas)}
        off, n = params["resultOffset"], params["resultRecordCount"]
        parte = self.filas[off:off + n]
        return {"features": [{"attributes": dict(f), "geometry": {"x": -74.8, "y": 10.7}} for f in parte],
                "exceededTransferLimit": off + n < len(self.filas)}


def correr():
    tmp = Path(tempfile.mkdtemp())
    storage.DATA = tmp / "data"
    reporte.DOCS = tmp / "docs"

    def con(filas):
        srv = FakeServidor(filas)
        extractor._get = srv
        return srv

    # Día 1: primer snapshot, paginado en 3 páginas
    srv = con(base())
    df1 = extractor.descargar()
    assert len(df1) == 5004 and df1["clave"].is_unique
    assert df1["fecha_entrada_operacion"].min() == pd.Timestamp("2024-11-30")
    assert df1.loc[df1["nombre_proyecto"] == "EOLICO X", "tipo_tecnologia"].iloc[0] == "EOLICA"
    assert srv.llamadas == 2 + 3
    assert main.actualizar(dt.date(2026, 11, 1), df=df1) == 0
    assert len(storage.snapshots()) == 1

    # Día 2: igual (solo cambia fecha_actualizacion) -> no se guarda snapshot nuevo
    filas2 = base()
    for f in filas2:
        f["fecha_actualizacion"] = "11/02/2026"
    con(filas2)
    assert main.actualizar(dt.date(2026, 11, 2), df=extractor.descargar()) == 0
    assert len(storage.snapshots()) == 1

    # Día 3: Guayepo III entra en operación, Puerta de Oro sube a 320 MW, un proyecto nuevo,
    # Eólico X desaparece, y objectids reasignados (no deben generar cambios falsos).
    filas3 = [dict(f, objectid=f["objectid"] + 7) for f in base() if f["nombre_proyecto"] != "EOLICO X"]
    filas3[2]["estado_proyecto"] = "EN OPERACIÓN"
    filas3[1]["capacidad_mw"] = 320
    filas3.append(_proyecto(9999, "SOLAR NUEVO", 19.9, "SOLAR", "EN PRUEBAS",
                            "Generacion Centralizada", "2026-11-03", "20001", "CESAR", "VALLEDUPAR"))
    con(filas3)
    n = main.actualizar(dt.date(2026, 11, 3), df=extractor.descargar())
    ev = storage.consulta("SELECT * FROM cambios")
    tipos = dict(zip(ev["nombre_proyecto"], ev["tipo_cambio"]))
    assert n == 4, ev
    assert tipos == {"GUAYEPO III": "cambio_estado", "PARQUE SOLAR PUERTA DE ORO": "cambio_mw",
                     "SOLAR NUEVO": "nuevo", "EOLICO X": "retirado"}
    assert ev.loc[ev["tipo_cambio"] == "cambio_mw", "delta_mw"].iloc[0] == pytest.approx(20)

    # Re-correr el mismo día no duplica nada
    main.actualizar(dt.date(2026, 11, 3), df=extractor.descargar())
    assert len(storage.consulta("SELECT * FROM cambios")) == 4
    assert storage.consulta("SELECT count(DISTINCT fecha) n FROM resumen_diario")["n"].iloc[0] == 3

    # Día 4: la capa viene a medias -> se rechaza y no se registran retiros
    con(base()[:1000])
    with pytest.raises(RuntimeError, match="caída"):
        main.actualizar(dt.date(2026, 11, 4), df=extractor.descargar())
    assert len(storage.consulta("SELECT * FROM cambios")) == 4

    # Campo obligatorio ausente -> error claro
    con([{k: v for k, v in f.items() if k != "capacidad_mw"} for f in base()[:5]])
    with pytest.raises(RuntimeError, match="capacidad_mw"):
        extractor.descargar()

    salida = reporte.generar()
    texto = salida.read_text(encoding="utf-8")
    assert "GUAYEPO III" in texto and "SOLAR NUEVO" in texto and "2026-11-03" in texto
    assert (reporte.DOCS / "datos" / "cambios_recientes.csv").exists()
    return salida


def test_pipeline():
    correr()


if __name__ == "__main__":
    print("OK", correr())
