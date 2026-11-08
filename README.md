# Monitor de instalación FNCER · Colombia

Seguimiento diario de los proyectos de fuentes no convencionales (solar, eólica, PCH...)
que UPME publica en el geovisor **Proyectos 6GW** (SIMEC · Seguimiento FNCER). Usa la
API REST pública de ArcGIS detrás del geovisor:

`https://geo.upme.gov.co/server/rest/services/Capas_EnergiaElectrica/proyectos_unificados_6gw/FeatureServer/23`

Mismo estilo que `monitor-fosil`: Parquet + DuckDB, reporte HTML con Plotly y GitHub Actions.

## Qué hace cada día

1. Descarga la capa completa (~29 mil registros, de a 2.000 por petición).
2. Valida que sigan existiendo los campos esperados; si UPME cambió la capa, falla con un error claro.
3. Guarda un resumen diario (MW y número de proyectos por tipo, tecnología y estado).
4. Si algo cambió frente al último snapshot, guarda la capa completa y registra los eventos por proyecto:
   **nuevo**, **ya no aparece**, **cambio de estado** (p. ej. pruebas → operación), **cambio de MW** y **cambio de fecha de entrada en operación**.
5. Regenera `docs/index.html`.

## Qué guarda

| Tabla | Ruta | Contenido |
|---|---|---|
| Snapshots | `data/snapshots/fecha=YYYY-MM-DD.parquet` | capa completa, solo los días en que cambió algo |
| Cambios | `data/cambios/anio=YYYY.parquet` | fecha, clave, tipo_cambio, proyecto, tipo, tecnología, estado, ubicación, capacidad_mw, delta_mw, valor_anterior, valor_nuevo |
| Resumen | `data/resumen_diario.parquet` | fecha, tipo_proyecto, tipo_tecnologia, estado_proyecto, proyectos, capacidad_mw |

Consulta con DuckDB: `storage.consulta("SELECT * FROM cambios WHERE tipo_cambio = 'cambio_estado'")`
(vistas `cambios`, `resumen_diario` y `proyectos` = último snapshot).

## Reporte (`docs/index.html`)

- KPIs: MW registrados, en operación, en pruebas, variación observada en 30 días.
- Capacidad acumulada por tecnología según la fecha de entrada en operación (histórico disponible desde el día 1).
- Capacidad observada día a día por estado (crece a medida que el monitor corre).
- Tabla de cambios de los últimos 30 días para proyectos ≥ 1 MW (los menores se resumen).
- Proyectos en pruebas ≥ 1 MW: lo que está por entrar.
- MW por tipo de proyecto y top de departamentos. CSV de cambios recientes en `docs/datos/`.

Umbrales y colores en `config/fuente.py`.

## Puesta en marcha

1. Crea el repo (p. ej. `monitor-fncer`), sube esta carpeta y activa
   Settings → Actions → General → *Read and write permissions*.
2. Prueba local: `pip install -r requirements.txt pytest && python -m pytest tests/ && python main.py`.
3. Actions → *Monitor instalación FNCER (UPME)* → Run workflow para la primera corrida.
4. Settings → Pages → `main` / `/docs` para publicar el reporte.

Corre todos los días a las 8:00 a.m. hora Colombia. Si UPME falla, igual guarda el
reporte con lo último disponible y deja la corrida en rojo para que GitHub te avise.

## Limitaciones a tener en cuenta

- **No es una API oficial documentada.** UPME puede renombrar la capa o sus campos; el monitor busca la capa por nombre y valida campos para que eso se note de inmediato.
- **No hay id estable por proyecto.** La clave es nombre + municipio + tipo + tecnología. Si UPME corrige el nombre de un proyecto, aparecerá como "ya no aparece" + "nuevo". Homónimos en el mismo municipio (frecuente en autogeneración pequeña) se numeran #2, #3…
- **Protección contra cargas a medias:** si la capa trae más de 20 % menos registros que el último snapshot, no registra nada y falla (`--forzar` para aceptarlo).
- Es un inventario de capacidad (MW), no generación. La generación sigue viniendo de XM.
- El primer día solo crea la línea base; los cambios empiezan a registrarse desde la segunda corrida.
