"""Comparación entre dos snapshots de la capa: qué proyectos entraron, salieron o cambiaron."""
import pandas as pd

COLS_INFO = ["clave", "nombre_proyecto", "tipo_proyecto", "tipo_tecnologia",
             "departamento", "municipio"]


def resumen(df, fecha):
    r = (df.groupby(["tipo_proyecto", "tipo_tecnologia", "estado_proyecto"], dropna=False)
           .agg(proyectos=("clave", "size"), capacidad_mw=("capacidad_mw", "sum"))
           .reset_index())
    r.insert(0, "fecha", pd.Timestamp(fecha))
    return r


def comparar(anterior, nuevo, fecha):
    """
    Una fila por evento. tipo_cambio:
      nuevo           aparece en la capa
      retirado        ya no aparece
      cambio_estado   p. ej. EN PRUEBAS -> EN OPERACIÓN
      cambio_mw       la capacidad cambió
      cambio_fecha    cambió la fecha de entrada en operación
    """
    a = anterior.set_index("clave")
    n = nuevo.set_index("clave")
    eventos = []

    def _ev(fila, tipo, antes, despues, delta):
        d = {c: fila.get(c) for c in COLS_INFO[1:]}
        d.update(clave=fila.name, tipo_cambio=tipo, valor_anterior=antes, valor_nuevo=despues,
                 capacidad_mw=fila.get("capacidad_mw"), delta_mw=delta,
                 estado_proyecto=fila.get("estado_proyecto"))
        eventos.append(d)

    for clave in n.index.difference(a.index):
        f = n.loc[clave]
        _ev(f, "nuevo", None, f["estado_proyecto"], f["capacidad_mw"])
    for clave in a.index.difference(n.index):
        f = a.loc[clave]
        _ev(f, "retirado", f["estado_proyecto"], None, -f["capacidad_mw"])

    comunes = n.index.intersection(a.index)
    va, vn = a.loc[comunes], n.loc[comunes]
    for clave in comunes[(va["estado_proyecto"].fillna("") != vn["estado_proyecto"].fillna("")).to_numpy()]:
        _ev(n.loc[clave], "cambio_estado", a.at[clave, "estado_proyecto"],
            n.at[clave, "estado_proyecto"], 0.0)
    dmw = (vn["capacidad_mw"].fillna(0) - va["capacidad_mw"].fillna(0))
    for clave in comunes[(dmw.abs() >= 0.001).to_numpy()]:
        _ev(n.loc[clave], "cambio_mw", str(a.at[clave, "capacidad_mw"]),
            str(n.at[clave, "capacidad_mw"]), float(dmw[clave]))
    fa, fn = va["fecha_entrada_operacion"], vn["fecha_entrada_operacion"]
    distintas = ~((fa == fn) | (fa.isna() & fn.isna()))
    for clave in comunes[distintas.to_numpy()]:
        _ev(n.loc[clave], "cambio_fecha", _d(fa[clave]), _d(fn[clave]), 0.0)

    cols = ["fecha", "clave", "tipo_cambio", "nombre_proyecto", "tipo_proyecto", "tipo_tecnologia",
            "estado_proyecto", "departamento", "municipio", "capacidad_mw", "delta_mw",
            "valor_anterior", "valor_nuevo"]
    if not eventos:
        return pd.DataFrame(columns=cols)
    out = pd.DataFrame(eventos)
    out["fecha"] = pd.Timestamp(fecha)
    for c in ("valor_anterior", "valor_nuevo"):
        out[c] = out[c].astype("string")
    return out[cols].sort_values(["tipo_cambio", "capacidad_mw"], ascending=[True, False])


def _d(x):
    return None if pd.isna(x) else pd.Timestamp(x).date().isoformat()
