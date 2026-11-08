"""Reporte HTML (Plotly) del avance de instalación de FNCER en Colombia."""
import datetime as dt
import html

import pandas as pd
import plotly.graph_objects as go

from config.fuente import (COLORES_ESTADO, COLORES_TECNOLOGIA, DIAS_CAMBIOS_REPORTE,
                           UMBRAL_MW_TABLA)
from src import storage

DOCS = storage.RAIZ / "docs"

ETIQ_CAMBIO = {
    "nuevo": "Nuevo", "retirado": "Ya no aparece", "cambio_estado": "Cambio de estado",
    "cambio_mw": "Cambio de capacidad", "cambio_fecha": "Cambio de fecha FPO",
}


def _fmt(x, dec=1):
    if x is None or pd.isna(x):
        return "–"
    return f"{x:,.{dec}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _e(x):
    return "" if x is None or pd.isna(x) else html.escape(str(x))


def _es(estado, palabra):
    return estado.fillna("").str.normalize("NFKD").str.encode("ascii", "ignore").str.decode("ascii").str.contains(palabra)


def _layout(fig, titulo, alto=420):
    fig.update_layout(title=titulo, template="plotly_white", height=alto,
                      margin=dict(l=10, r=10, t=50, b=40), legend=dict(orientation="h", y=-0.18))
    return fig


def _color_tec(t):
    return COLORES_TECNOLOGIA.get(t, COLORES_TECNOLOGIA["OTRA"])


def _g_acumulada(p):
    """Curva histórica reconstruida con la fecha de entrada en operación de cada proyecto."""
    d = p.dropna(subset=["fecha_entrada_operacion"]).copy()
    d["mes"] = d["fecha_entrada_operacion"].dt.to_period("M").dt.to_timestamp()
    m = d.pivot_table(index="mes", columns="tipo_tecnologia", values="capacidad_mw",
                      aggfunc="sum", fill_value=0).sort_index().cumsum()
    fig = go.Figure()
    for t in m.columns:
        fig.add_trace(go.Scatter(x=m.index, y=m[t], name=t.title(), stackgroup="uno",
                                 line=dict(color=_color_tec(t), width=0.5),
                                 hovertemplate=f"{t.title()}: %{{y:,.1f}} MW<extra></extra>"))
    fig.update_layout(hovermode="x unified")
    fig.update_yaxes(title_text="MW acumulados")
    return _layout(fig, "Capacidad acumulada según fecha de entrada en operación (operación + pruebas)")


def _g_observada(resumen):
    r = resumen.copy()
    r["estado"] = r["estado_proyecto"].fillna("SIN ESTADO")
    s = r.pivot_table(index="fecha", columns="estado", values="capacidad_mw", aggfunc="sum").sort_index()
    fig = go.Figure()
    for e in s.columns:
        fig.add_trace(go.Scatter(x=s.index, y=s[e], name=e.title(), mode="lines+markers",
                                 stackgroup="uno", line=dict(color=COLORES_ESTADO.get(e)),
                                 hovertemplate=f"{e.title()}: %{{y:,.1f}} MW<extra></extra>"))
    fig.update_layout(hovermode="x unified")
    fig.update_yaxes(title_text="MW")
    return _layout(fig, "Capacidad registrada en la capa de UPME, día a día (lo que observa este monitor)", 380)


def _g_tipo(p):
    t = p.pivot_table(index="tipo_proyecto", columns="estado_proyecto", values="capacidad_mw",
                      aggfunc="sum", fill_value=0)
    t = t.loc[t.sum(axis=1).sort_values().index]
    fig = go.Figure([go.Bar(y=t.index, x=t[e], name=str(e).title(), orientation="h",
                            marker_color=COLORES_ESTADO.get(e),
                            hovertemplate="%{y}: %{x:,.1f} MW<extra>" + str(e).title() + "</extra>")
                     for e in t.columns])
    fig.update_layout(barmode="stack")
    return _layout(fig, "MW por tipo de proyecto y estado", max(320, 50 * len(t) + 140))


def _g_dpto(p, n=15):
    t = p.pivot_table(index="departamento", columns="tipo_tecnologia", values="capacidad_mw",
                      aggfunc="sum", fill_value=0)
    t = t.loc[t.sum(axis=1).sort_values().tail(n).index]
    fig = go.Figure([go.Bar(y=t.index, x=t[c], name=c.title(), orientation="h",
                            marker_color=_color_tec(c),
                            hovertemplate="%{y}: %{x:,.1f} MW<extra>" + c.title() + "</extra>")
                     for c in t.columns])
    fig.update_layout(barmode="stack")
    return _layout(fig, f"Top {n} departamentos por MW", 30 * len(t) + 160)


def _tabla_cambios(c):
    if c.empty:
        return "<tr><td colspan='9'>Sin cambios registrados en el periodo.</td></tr>"
    filas = []
    for r in c.itertuples():
        filas.append(
            f"<tr><td>{pd.Timestamp(r.fecha).date()}</td><td>{ETIQ_CAMBIO.get(r.tipo_cambio, r.tipo_cambio)}</td>"
            f"<td>{_e(r.nombre_proyecto)}</td><td>{_e(r.tipo_proyecto)}</td><td>{_e(str(r.tipo_tecnologia).title())}</td>"
            f"<td>{_e(r.municipio)}, {_e(r.departamento)}</td><td class='n'>{_fmt(r.capacidad_mw, 2)}</td>"
            f"<td>{_e(r.valor_anterior) or '–'} → {_e(r.valor_nuevo) or '–'}</td>"
            f"<td class='n'>{_fmt(r.delta_mw, 2)}</td></tr>")
    return "\n".join(filas)


def _tabla_pruebas(p):
    t = p[_es(p["estado_proyecto"], "PRUEBA") & (p["capacidad_mw"] >= UMBRAL_MW_TABLA)]
    t = t.sort_values("capacidad_mw", ascending=False)
    if t.empty:
        return "<tr><td colspan='6'>No hay proyectos en pruebas sobre el umbral.</td></tr>"
    return "\n".join(
        f"<tr><td>{_e(r.nombre_proyecto)}</td><td>{_e(r.tipo_proyecto)}</td>"
        f"<td>{_e(str(r.tipo_tecnologia).title())}</td><td>{_e(r.municipio)}, {_e(r.departamento)}</td>"
        f"<td class='n'>{_fmt(r.capacidad_mw, 2)}</td>"
        f"<td>{'' if pd.isna(r.fecha_entrada_operacion) else pd.Timestamp(r.fecha_entrada_operacion).date()}</td></tr>"
        for r in t.itertuples())


def _delta_operacion(resumen, dias):
    r = resumen[_es(resumen["estado_proyecto"], "OPERACION")]
    s = r.groupby("fecha")["capacidad_mw"].sum().sort_index()
    if len(s) < 2:
        return None, None
    ultima = s.index[-1]
    previas = s[s.index <= ultima - pd.Timedelta(days=dias)]
    base_fecha = previas.index[-1] if len(previas) else s.index[0]
    return s.iloc[-1] - s[base_fecha], base_fecha


def generar():
    fecha_snap, p = storage.ultimo_snapshot()
    if p is None:
        raise RuntimeError("No hay snapshots en data/snapshots. Corre main.py primero.")
    resumen = storage.consulta("SELECT * FROM resumen_diario ORDER BY fecha")
    fecha = pd.Timestamp(resumen["fecha"].max()).date()
    desde = pd.Timestamp(fecha) - pd.Timedelta(days=DIAS_CAMBIOS_REPORTE)
    try:
        cambios = storage.consulta(f"SELECT * FROM cambios WHERE fecha > TIMESTAMP '{desde}'")
    except Exception:  # noqa: BLE001 - aún no hay tabla de cambios
        cambios = pd.DataFrame(columns=["fecha", "tipo_cambio", "capacidad_mw", "delta_mw"])

    oper = p.loc[_es(p["estado_proyecto"], "OPERACION"), "capacidad_mw"].sum()
    prueb = p.loc[_es(p["estado_proyecto"], "PRUEBA"), "capacidad_mw"].sum()
    d30, base = _delta_operacion(resumen, 30)
    kpis = [
        ("Capacidad FNCER registrada", f"{_fmt(p['capacidad_mw'].sum())} MW"),
        ("En operación", f"{_fmt(oper)} MW"),
        ("En pruebas", f"{_fmt(prueb)} MW"),
        ("Registros en la capa", f"{len(p):,}".replace(",", ".")),
        ("Δ en operación (observado)",
         "– (falta histórico)" if d30 is None else f"{'+' if d30 >= 0 else ''}{_fmt(d30)} MW desde {base.date()}"),
    ]
    kpi_html = "".join(f"<div class='kpi'><div class='k'>{k}</div><div class='v'>{v}</div></div>" for k, v in kpis)

    grandes = cambios[cambios["capacidad_mw"].fillna(0) >= UMBRAL_MW_TABLA].sort_values(
        ["fecha", "capacidad_mw"], ascending=[False, False])
    chicos = cambios[cambios["capacidad_mw"].fillna(0) < UMBRAL_MW_TABLA]
    nota_chicos = ""
    if len(chicos):
        por_tipo = chicos.groupby("tipo_cambio")["delta_mw"].agg(["size", "sum"])
        nota_chicos = "Además, cambios en proyectos de menos de {} MW: {}.".format(
            _fmt(UMBRAL_MW_TABLA, 0),
            "; ".join(f"{ETIQ_CAMBIO.get(t, t).lower()}: {n} ({'+' if s >= 0 else ''}{_fmt(s, 2)} MW)"
                      for t, (n, s) in por_tipo.iterrows()))

    graficas = [_g_acumulada(p), _g_observada(resumen), _g_tipo(p), _g_dpto(p)]
    g_html = [graficas[0].to_html(full_html=False, include_plotlyjs="cdn")] + \
             [g.to_html(full_html=False, include_plotlyjs=False) for g in graficas[1:]]

    pagina = PLANTILLA.format(
        fecha=fecha, fecha_snap=fecha_snap.date(), kpis=kpi_html,
        g1=g_html[0], g2=g_html[1], g3=g_html[2], g4=g_html[3],
        dias=DIAS_CAMBIOS_REPORTE, umbral=_fmt(UMBRAL_MW_TABLA, 0),
        filas_cambios=_tabla_cambios(grandes), nota_chicos=_e(nota_chicos),
        filas_pruebas=_tabla_pruebas(p),
        generado=dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
    )
    (DOCS / "datos").mkdir(parents=True, exist_ok=True)
    (DOCS / "index.html").write_text(pagina, encoding="utf-8")
    cambios.to_csv(DOCS / "datos" / "cambios_recientes.csv", index=False)
    return DOCS / "index.html"


PLANTILLA = """<!doctype html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Monitor FNCER {fecha}</title>
<style>
 body{{font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;margin:0;background:#f6f7f9;color:#1d1d1f}}
 main{{max-width:1100px;margin:0 auto;padding:16px}}
 h1{{font-size:1.4rem;margin:8px 0 4px}} h2{{font-size:1.05rem;margin:4px 6px 8px}} .sub{{color:#666;margin-bottom:16px}}
 .kpis{{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:10px;margin-bottom:16px}}
 .kpi{{background:#fff;border-radius:10px;padding:12px 14px;box-shadow:0 1px 2px #0001}}
 .k{{font-size:.8rem;color:#666}} .v{{font-size:1.2rem;font-weight:600;margin-top:4px}}
 .card{{background:#fff;border-radius:10px;padding:8px;margin-bottom:16px;box-shadow:0 1px 2px #0001;overflow-x:auto}}
 .scroll{{max-height:520px;overflow:auto}}
 table{{border-collapse:collapse;width:100%;font-size:.85rem}}
 th,td{{padding:6px 8px;border-bottom:1px solid #eee;text-align:left;white-space:nowrap}}
 th{{background:#fafafa;position:sticky;top:0}} td.n{{text-align:right;font-variant-numeric:tabular-nums}}
 .nota{{color:#555;font-size:.8rem;margin:8px 6px}}
 footer{{color:#888;font-size:.75rem;margin:16px 0}}
</style></head><body><main>
<h1>Instalación de FNCER en Colombia · {fecha}</h1>
<div class="sub">Proyectos de fuentes no convencionales (solar, eólica, PCH, etc.) en operación y en pruebas.
Fuente: UPME, capa <em>proyectos_unificados_6gw</em> del geovisor Proyectos 6GW (SIMEC). Último cambio detectado en la capa: {fecha_snap}.</div>
<div class="kpis">{kpis}</div>
<div class="card">{g1}</div>
<div class="card">{g2}</div>
<div class="card"><h2>Cambios en los últimos {dias} días (proyectos de {umbral} MW o más)</h2><div class="scroll"><table>
<thead><tr><th>Fecha</th><th>Cambio</th><th>Proyecto</th><th>Tipo</th><th>Tecnología</th><th>Ubicación</th>
<th>MW</th><th>Antes → ahora</th><th>Δ MW</th></tr></thead>
<tbody>{filas_cambios}</tbody></table></div><div class="nota">{nota_chicos}</div></div>
<div class="card"><h2>En pruebas ({umbral} MW o más): lo que está por entrar</h2><div class="scroll"><table>
<thead><tr><th>Proyecto</th><th>Tipo</th><th>Tecnología</th><th>Ubicación</th><th>MW</th><th>Fecha FPO</th></tr></thead>
<tbody>{filas_pruebas}</tbody></table></div></div>
<div class="card">{g3}</div>
<div class="card">{g4}</div>
<footer>Generado {generado}. Cambios recientes en <a href="datos/cambios_recientes.csv">CSV</a>;
histórico completo en data/ (snapshots, cambios y resumen diario en Parquet).
La curva acumulada se reconstruye con la fecha de entrada en operación que reporta UPME;
la curva "observada" solo cubre los días desde que este monitor empezó a correr.</footer>
</main></body></html>
"""
