# Session handoff — 2026-05-26

Última sesión cerró la **Opción C**: Athena workgroup `olist-dev` provisionado y tabla
`staging_orders` registrada en el Catalog vía `CREATE EXTERNAL TABLE` con partition
projection. Smoke test pasado contra AWS real (99.441 filas, 25 particiones).
Este documento es para retomar el trabajo sin re-descubrir el estado. Sobreescribible:
la próxima sesión lo actualiza al cerrar.

## Estado vivo en AWS (eu-west-1, account <account-id>)

- **4 S3 buckets**: `olist-raw-01`, `olist-staging-01`, `olist-curated-01`,
  `olist-athena-results-01`. Todos privados, encriptados SSE-S3, con las 3 tags
  obligatorias. Versioning OFF.
- **Raw ingestado**: 9 tablas Olist en
  `s3://olist-raw-01/source=<tabla>/ingested_at=2026-05-20/*.csv.gz`.
- **Glue Catalog**: database `olist_dev` con 9 tablas `raw_source_*` (columnas como
  `col0..col7` por quirk conocido del Crawler con CSVs gzipped — intencional, ver
  `docs/architecture.md`). Particiones `ingested_at` descubiertas correctamente.
- **IAM role** `olist-glue-role` con dos inline policies: `olist-glue-s3-read-raw` y
  `olist-glue-s3-staging` (R+W+Delete+PutObjectTagging).
- **Glue Job** `olist-staging-orders` (Glue 5.0, 2× G.1X, ON_DEMAND, MaxRetries=0,
  `--additional-python-modules` con boto3>=1.36 para conditional PUT).
- **Staging output**: 25 particiones Parquet+Snappy en
  `s3://olist-staging-01/source=orders/year=YYYY/month=MM/*.parquet`, cubriendo
  2016-09 → 2018-10. HWM state file en `_metadata/staging_orders_state.json`.
- **Athena workgroup** `olist-dev` (NUEVO): cap 1 GiB/query, SSE_S3, result location
  `s3://olist-athena-results-01/`, `EnforceWorkGroupConfiguration=true`,
  CloudWatch metrics OFF. Provisionado por `infra/create-athena-workgroup.sh`.
- **Tabla Catalog** `olist_dev.staging_orders` (NUEVO): registrada vía
  `CREATE EXTERNAL TABLE` (no Crawler) con partition projection sobre `year`/`month`.
  Provisionada por `infra/create-staging-tables.sh`. Consultable: 99.441 filas,
  25 particiones verificadas. Ver `docs/architecture.md` → "Staging table registration".

## Gap del pipeline

Solo `orders` está en staging Y registrado en Athena. Faltan **8 tablas**
(`order_items`, `order_payments`, `order_reviews`, `customers`, `sellers`, `products`,
`geolocation`, `product_category_name_translation`) — ni en staging ni registradas.

También faltan: curated star-schema (`fact_*`, `dim_*`), orquestación EventBridge+Lambda,
dashboard Power BI.

## Dos opciones para continuar (C ya hecho)

### Opción A — Replicar staging para las 8 tablas restantes
- **Scope**: 1 módulo de transformación + 1 Glue Job por tabla (decisión pendiente:
  ¿uno parametrizable con `--SOURCE_TABLE` o 8 jobs? — voto previo: parametrizable,
  va a ADR formal por ser modelo operacional). Mismo patrón que `staging_orders`
  (HWM, dedup, Parquet+Snappy particionado). Cada tabla nueva suma un
  `CREATE EXTERNAL TABLE` en `create-staging-tables.sh` (patrón ya establecido en C).
- **Riesgo**: bajo. Patrón probado. Solo varía el schema por tabla.
- **Tiempo**: 1–2 sesiones.
- **Recomendable si** querés completar la capa staging entera antes de tocar curated.

### Opción B — Saltar a curated star-schema
- **Scope**: definir `fact_orders`, `fact_order_items`, `dim_customers`, `dim_products`,
  `dim_sellers`, `dim_geolocation`, `dim_date`, `dim_currency`. Glue Jobs de curated
  leen staging, hacen joins, enriquecen con FX rates (Frankfurter API), escriben
  Parquet particionado por `year/month` en facts.
- **Riesgo**: medio. Curated es donde aparecen los joins — mismatches de schema afloran
  acá. Y requiere las 8 staging tables pendientes (opción A) como dependencia.
- **Tiempo**: 2–3 sesiones (asumiendo A hecho).
- **Recomendable si** el goal es ver KPIs en Athena/Power BI lo antes posible.

**Sugerencia**: A es la dependencia natural de B (curated necesita las 8 staging tables
para los joins). El camino recto al dashboard es A → B. El patrón de registro en Athena
ya quedó demostrado con C, así que A ahora incluye "replicar staging + registrar tabla"
como una unidad por cada source.

## Costo acumulado hasta hoy

~$0.15 total (sesión C sumó ~$0: workgroup gratis, queries de smoke test escanearon MBs,
muy bajo el free tier). Pipeline idle: ~$0/mes (todo ON_DEMAND, sin schedules).
Recordatorio: tracking manual de costos (sin budget alerts) — `aws ce get-cost-and-usage`
cada par de días.

## Archivos de referencia para retomar

- `CLAUDE.md` — ground rules del proyecto.
- `docs/adr/` — 7 ADRs (especialmente 0002 medallion, 0006 HWM, 0007 Iceberg).
- `docs/architecture.md` — naming conventions + production deltas + notas raw Catalog +
  config del Athena workgroup + convención de registro de staging tables (Tier B).
- `docs/glossary.md` — diccionario de conceptos con analogías Qlik/SQL (incluye ahora
  CREATE EXTERNAL TABLE, partition projection, MSCK REPAIR, Athena query lifecycle, Trino).
- `docs/INCREMENTAL_LOADS.md` — guía operacional del HWM (todavía sin consultar).
- `C:\Users\ferna\.claude\projects\d--Proyectos-infra-aws-powerbi-python\memory\MEMORY.md`
  — 3 memory files: no insistir con `budgets.sh`, desempacar conceptos inline +
  glossary, analogías en Qlik no Power BI.
