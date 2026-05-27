# Glosario del proyecto olist-bi-pipeline

Diccionario de los conceptos que vamos incorporando en la construcción del pipeline.
Si te aparece un término en chat o en código y no lo recordás, buscalo acá.

> Convención: explicación en español, términos técnicos en inglés (igual que en chat).
> Para el "por qué" profundo de cada decisión, ver el ADR correspondiente en `docs/adr/`.

**Última actualización:** 2026-05-26

---

## 1. AWS — infraestructura

### S3 bucket
Almacenamiento de objetos de AWS. Cada bucket tiene un nombre **globalmente único** en todo
AWS. En este proyecto hay 4 buckets: `olist-raw-01`, `olist-staging-01`, `olist-curated-01`,
`olist-athena-results-01`. Están privados, encriptados (SSE-S3), con versioning OFF.

### Tagging de recursos
Pares `key=value` que se asocian a un recurso AWS. Permiten filtrar cost reports.
En este proyecto, **3 tags son obligatorias** en todo recurso provisionado:
`project=olist-pipeline`, `env=dev`, `owner=marianela`.
Ver [`.claude/skills/aws-cost-discipline/SKILL.md`](../.claude/skills/aws-cost-discipline/SKILL.md).

### IAM (Identity and Access Management)
El sistema de permisos de AWS. Define quién puede hacer qué sobre qué recursos.
- **User**: identidad humana (vos), con access keys.
- **Role**: identidad que un servicio (Glue, Lambda) asume temporalmente para actuar en tu nombre.
- **Policy**: documento JSON que define permisos. Se adjunta a un role.
- **Trust policy**: parte del role que dice qué servicio puede asumirlo (ej: `glue.amazonaws.com`).
- **Permission policy**: qué puede hacer el role una vez asumido.
- **Managed policy**: policy mantenida por AWS (ej: `AWSGlueServiceRole`).
- **Inline policy**: policy embebida directamente en el role, para permisos custom muy específicos.

Analogía Qlik: como el Service Account que Qlik usa para conectarse a las DBs — una identidad
de servicio con permisos acotados a lo que necesita.

### IAM eventual consistency
Cuando creás un role nuevo, AWS tarda 5–30 segundos en propagar la información a otros
servicios. Si en ese lapso intentás usarlo (ej: crear un Crawler con ese role), AWS
responde "Service is unable to assume provided role". Fix estándar: retry con backoff.

### Glue Data Catalog
Almacén centralizado de **metadata** en AWS. NO guarda datos — solo descripciones (tablas,
columnas, ubicación en S3, particiones). Athena, Spark y Redshift Spectrum lo consultan.

Analogía SQL: como un `information_schema` global. Analogía Qlik: como las declaraciones de
tabla en el script de carga, pero compartidas entre servicios.

### Glue Database
Contenedor lógico dentro del Data Catalog. Agrupa tablas. En este proyecto usamos `olist_dev`.

### Glue Crawler
Servicio administrado que escanea archivos en S3, infiere su schema, y registra tablas en el
Data Catalog. **No mueve datos** — solo escribe metadata.

Cost shape: $0.44/DPU-hora, mínimo 10 min facturados. Para 9 CSVs chicos: ~$0.007 por run.
**Nunca con schedule** — siempre ON_DEMAND.

### Glue Classifier
Reglas que el Crawler usa para interpretar archivos. Se pueden definir custom (ej:
`olist-csv-with-header` que dice "estos CSV tienen header en la primera fila"). El matching
contra CSVs gzipped a veces falla — caso conocido del proyecto, ver
[`docs/architecture.md`](architecture.md).

### Glue Job
Proceso administrado que ejecuta código PySpark sobre un cluster Spark que AWS levanta y baja
por vos. Es donde corren las transformaciones raw→staging→curated.

Cost shape: $0.44/DPU-hora, mínimo 1 min facturado. Para Olist en 2 DPUs durante 5 min:
~$0.07 por run.

Analogía Qlik: una reload task — corre un script y produce output.

### Glue version
Versión de runtime del cluster Spark de Glue. Las relevantes:
- **5.0** (la que usamos): Python 3.11 + Spark 3.5.
- **4.0**: Python 3.10 + Spark 3.3.

Importante porque nuestro código usa `datetime.UTC` y `StrEnum` (Python 3.11+) — Glue 4.0
rompe, 5.0 funciona.

### Worker type (G.1X / G.2X)
Tamaño del worker en Glue Job. `G.1X` = 1 DPU = 4 vCPU + 16 GB RAM. `G.2X` = 2 DPUs. Para
Olist usamos **2 workers de tipo G.1X** (mínimo y suficiente).

### `--extra-py-files`
Argumento de Glue Job que apunta a un zip en S3 con el código de tu librería. Glue lo
agrega al `sys.path` del worker para que `from olist_pipeline.transformation... import ...`
funcione. Nuestro `create-glue-job-staging-orders.sh` empaqueta `src/olist_pipeline/` en
un zip y lo sube a `s3://staging/_glue-jobs/olist_pipeline.zip`.

### `--additional-python-modules`
Argumento de Glue Job que instala paquetes pip extra en el worker al arrancar. Formato:
`"boto3>=1.36.0,botocore>=1.36.0"`. Lo usamos en `staging-orders` porque la versión de
boto3 que viene en Glue 5.0 no soporta `IfMatch`/`IfNoneMatch` en `put_object` (feature
de S3 conditional writes de fines de 2024, posterior al boto3 bundleado). Sumamos ~30s
al cold start.

### `getResolvedOptions` (awsglue)
Función de la librería `awsglue.utils` que parsea los args del Glue Job. Cada arg se pasa
como `--ARG_NAME value` y queda accesible vía `args["ARG_NAME"]`. Glue inyecta `JOB_NAME`
automáticamente; los demás los declarás en `--default-arguments` del job spec.

### `GlueContext` / `job.init` / `job.commit`
Boilerplate del runtime de Glue. `GlueContext` envuelve el `SparkContext` con utilidades
Glue-específicas (DynamicFrame, Job bookmarks). `job.init(name, args)` registra el run;
`job.commit()` lo marca como terminado para el accounting de Glue. Si tu wrapper sale por
excepción sin llegar a `job.commit()`, el run figura como FAILED.

### Glue Job bookmarks
Mecanismo built-in de Glue para tracking incremental — recuerda qué archivos procesó el
último run y los salta en el siguiente. **Lo deshabilitamos**
(`--job-bookmark-option=job-bookmark-disable`) porque ya tenemos HWM propio en S3
(ADR-0006), inspectable y portátil fuera de Glue.

### DPU (Data Processing Unit)
Unidad de compute de Glue. 1 DPU = 4 vCPU + 16 GB RAM. Glue Jobs sobre Olist usan **2 DPUs**
(mínimo de Glue, y suficiente para este volumen). Subir DPUs sin razón es plata tirada.

### Athena
Motor de consulta SQL serverless de AWS. Ejecuta SQL sobre archivos en S3 a través del Data
Catalog, sin cluster. Cost shape: $5 por TB escaneado; primer TB/mes gratis en free tier.
Ver [ADR-0001](adr/0001-athena-over-redshift.md).

### Athena workgroup
Configuración de Athena que agrupa queries: dónde escribir resultados, límite de bytes
escaneados, cache de resultados. Tenemos uno: `olist-dev` con cap de 1 GB por query,
`EnforceWorkGroupConfiguration=true` (los clientes no pueden saltearse el cap). Ver
[`docs/architecture.md`](architecture.md) → "Athena workgroup configuration".

### CREATE EXTERNAL TABLE
Comando SQL (sintaxis Hive) que ejecutás contra Athena para **registrar una tabla en el Glue
Catalog apuntando a archivos en S3**. "External" significa que los datos viven afuera (en S3)
y el Catalog solo guarda la receta para leerlos: columnas, tipos, ubicación, formato. Borrar
la tabla (`DROP TABLE`) elimina solo la metadata, **nunca** los datos en S3.

Analogía Qlik: como un `LOAD * FROM [archivo]` con su schema declarado — los datos no se copian
a ningún lado, se leen on-demand cuando hay una query.

En este proyecto registramos staging/curated con DDL explícito en vez de Crawler: el Parquet
ya trae schema embebido, así que no hay nada que *inferir*, solo que *declarar*. Cuesta $0 y
evita sorpresas tipo `col0..col7`. Ver [`infra/create-staging-tables.sh`](../infra/create-staging-tables.sh).

### Partition projection
Feature de Athena para tablas particionadas: en vez de descubrir las particiones escaneando
S3, le declarás por adelantado el **rango de valores** (ej: `year` 2016–2030, `month` 1–12) y
un **template de path** (`.../year=${year}/month=${month}`). Athena calcula las particiones al
vuelo, sin escanear. **Cero mantenimiento** — no hay paso post-run que se pueda olvidar.

Analogía Qlik: como un loop `FOR vYear = 2016 TO 2030 / FOR vMonth = 1 TO 12` que arma los
paths de los QVDs por patrón de nombre, en vez de hacer un dir-listing del disco.

Gotcha del proyecto: Spark escribe las particiones int **sin zero-padding** (`month=9`, no
`month=09`), así que el projection no declara `digits`. Si una query devuelve 0 filas con datos
presentes en S3, sospechar primero de un mismatch de padding acá.

### MSCK REPAIR TABLE
La alternativa a partition projection (la que **no** usamos). Comando que escanea el bucket
buscando paths `key=value/` y registra las particiones encontradas en el Catalog. Hay que
re-correrlo cada vez que aparecen particiones nuevas (ej: después de cada run del Glue Job) —
frágil porque es un paso manual fácil de olvidar. Projection lo vuelve innecesario.

### Athena query lifecycle (asíncrono)
Athena **no** devuelve el resultado en la misma llamada que lanza la query. El ciclo es:
1. `start-query-execution` → dispara la query y devuelve un **`QueryExecutionId`** (un ticket).
2. `get-query-execution` → consultás el estado con ese id: `QUEUED` → `RUNNING` →
   `SUCCEEDED` / `FAILED` / `CANCELLED`. Hay que **pollear** (loop con `sleep`) hasta un
   estado terminal. Si es `FAILED`, el campo `StateChangeReason` dice por qué.
3. `get-query-results` → recién ahí traés las filas, usando el mismo id.

Por eso los scripts (`create-staging-tables.sh`) tienen una función `run_athena_query` con un
loop de polling en vez de un solo comando. DDL (CREATE/DROP) termina en ~1–3s; un SELECT
pesado puede tardar más.

Analogía Qlik: una reload task no es instantánea — la disparás y después consultás su estado
(`Triggered` → `Started` → `Finished`/`Failed`) en la QMC o por la API. Athena es igual: lanzás,
consultás estado, recogés resultado. No es un `SELECT` síncrono como contra una DB tradicional.

### Trino / Presto (motor SQL de Athena)
Athena por dentro es **Trino** (antes llamado Presto), un motor SQL distribuido open-source.
Su dialecto SQL no es idéntico al de otras DBs y es **estricto con los tipos** — no castea
implícitamente como otros motores.

Gotcha que ya nos mordió: el operador de concatenación `||` exige **strings**, no acepta enteros.
`year || '-' || month` con `year`/`month` INT falla con `FUNCTION_NOT_FOUND ... concat`. Hay que
castear: `CAST(year AS varchar) || '-' || CAST(month AS varchar)`. Regla general: en Trino, si
mezclás tipos en una función, casteá explícito.

### Lambda
Función serverless que corre código Python en respuesta a eventos. Cost shape: prácticamente
gratis a portfolio scale. **Cuidado con triggers recursivos** (Lambda → S3 → Lambda → ...).

### EventBridge
Servicio de routing de eventos de AWS. Conecta servicios entre sí (ej: "cuando termina este
Glue Job, dispará esta Lambda"). Prácticamente gratis.

### Budget alerts
Alertas de costo que AWS te manda por email cuando proyecta superar un umbral. La skill
`aws-cost-discipline` define una escalera de 3 ($5 / $20 / $50). En este proyecto vos elegiste
tracking manual de costos en vez de budgets activos, así que el reflex Friday teardown importa
más (ver más abajo).

---

## 2. Data engineering — formatos y patrones

### CSV (Comma-Separated Values)
Formato de texto plano, por filas. Cada fila es una línea, columnas separadas por coma. Sin
tipos: todo es string hasta que parseás. Tamaño grande.

### Parquet
Formato binario **columnar** con schema embebido. Mucho más chico que CSV (con compresión
Snappy, ~5–10× menos). Lectura selectiva por columna (Athena lee solo lo que pediste).
Tipos nativos: `int`, `string`, `timestamp`, `decimal`.

### Parquet "tipado"
Cuando escribimos Parquet declaramos tipos explícitos por columna. El consumidor (Athena,
Power BI) ya **sabe** que `order_purchase_timestamp` es un `timestamp` nativo, no tiene que
parsear strings.

### Snappy
Algoritmo de compresión default de Parquet. Más rápido que gzip, comprime un poco menos.
Balance óptimo para análisis.

### Gzip
Algoritmo de compresión usado sobre CSVs en este proyecto (raw layer). Más lento que Snappy
pero comprime más.

### Particionamiento Hive-style
Convención donde las claves de partición aparecen en el path como `key=value/`. Ejemplo:
`s3://bucket/source=orders/ingested_at=2026-05-20/file.csv.gz`. Athena/Glue entienden esto
automáticamente y crean columnas virtuales.
Beneficio: **partition pruning** — al filtrar `WHERE ingested_at = '2026-05-20'` el motor lee
solo los archivos de esa partición, no todo el bucket.

### Medallion architecture
Patrón de 3 capas en S3 que usamos (ADR-0002):
- **raw/**: CSV+gzip, append-only, fiel a la fuente.
- **staging/**: Parquet tipado, limpio, deduplicado.
- **curated/**: Parquet star-schema, lo que Athena y Power BI consultan.

Los nombres bronze/silver/gold son sinónimos comerciales de raw/staging/curated.

### Dedup (deduplicación)
Eliminar filas duplicadas. En staging hacemos dedup por primary key (ej: `order_id`) — si la
misma fila apareció en dos particiones de raw, te quedás con la más reciente por
`ingested_at`.

Analogía SQL: `SELECT DISTINCT` o `ROW_NUMBER() OVER (PARTITION BY id ORDER BY ts DESC) = 1`.

**Patrón en PySpark** (el que usamos en `transformation/staging_orders.py`):
```python
w = Window.partitionBy("order_id").orderBy(F.col("ingested_at").desc())
df.withColumn("_rn", F.row_number().over(w)).where("_rn = 1").drop("_rn")
```
`Window` es el equivalente Spark de `OVER (PARTITION BY ... ORDER BY ...)` en SQL.

### Late-arriving data
Filas con fecha de negocio vieja (ej: `purchase_timestamp = 2017-10-15`) que llegan al lake
hoy (`ingested_at = 2026-05-22`). El staging Job tiene que procesarlas igual aunque sean
viejas — por eso filtramos por `ingested_at > hwm`, **NO** por `purchase_timestamp > hwm`.
Anti-pattern crítico del proyecto.

### HWM (High Water Mark)
"Señalador" que dice "ya procesé todo lo ingestado hasta acá". Se guarda en un archivo JSON
en S3 (`_metadata/staging_orders_state.json`). Cada run del Job lo lee al arrancar y lo
actualiza al finalizar.

Dos watermarks en este proyecto (ADR-0006):
- `ingestion_hwm`: max `ingested_at` procesado. Siempre avanza.
- `business_hwm`: max `purchase_timestamp` visto. Puede no avanzar si llegó data vieja.

### Incremental load
Patrón donde cada run del pipeline procesa **solo lo nuevo** desde la última run exitosa.
Opuesto a full reload (que reprocesa todo cada vez). HWM es el mecanismo que habilita
incremental load. Ver [ADR-0006](adr/0006-incremental-ingestion-hwm.md).

### `_SUCCESS` marker
Archivo vacío que Spark/Hadoop escriben al final de una partición exitosa. Convención: si
existe, la partición está completa y se puede consumir. En este proyecto, el PUT del `_SUCCESS`
triggea la próxima Lambda en la cadena de orquestación.

### Idempotencia
Una operación es idempotente si correrla **N veces produce el mismo resultado que correrla una
vez**, sin romper. Aplicaciones en este proyecto:
- **Ingesta**: re-correr el mismo día no duplica objetos (`head_object` antes de cada PUT).
- **Staging Job**: re-correr no duplica filas (overwrite del partition).
- **Scripts infra**: re-correr no rompe (si el recurso existe, skip + re-asserción).

### Atomic write con S3 ETag (`If-Match`)
Para evitar que dos runs concurrentes corrompan un state file, usamos `If-Match: <ETag>` en
el PUT. Si el ETag esperado no matchea (porque alguien escribió en el medio), AWS rechaza el
PUT con `412 Precondition Failed`. Solo un escritor gana.

### `StateConflictError` (HWM)
Excepción que tira `transformation.hwm.write_state` cuando el `If-Match`/`If-None-Match`
falla. Señaliza que **otro escritor modificó el state file entre tu read y tu write**, así
que tu HWM en memoria es stale. El caller debe abortar la corrida (no reintentar a ciegas:
los datos ya filtrados pueden estar mal).

### `If-None-Match: *` (S3)
Variante de la familia conditional PUT: "subí este objeto **solo si no existe ya**". Lo
usamos en la PRIMERA escritura del HWM state file (ETag previo = None → no podemos pasar
`If-Match`, pero igual queremos atomicidad por si dos primeras corridas pisan).

### `head_object` vs `If-None-Match`
Dos formas de implementar idempotencia en S3 PUT:
- **`head_object`** (la que usamos): chequeás antes si el objeto existe; si sí, skip. Cuesta
  1 request extra. Más legible.
- **`If-None-Match: *`**: header en el PUT mismo: "subí solo si no existe". 1 request menos
  pero más mágico.

### Schema-on-read vs schema-on-write
- **Schema-on-read** (raw layer): los archivos no tienen schema fuerte; cada consumidor lo
  interpreta. Es lo que pasa con los CSV de raw — la "interpretación" la hace el Glue Crawler
  o `spark.read.csv(header=True)`.
- **Schema-on-write** (staging+curated): el schema se define al escribir y queda embebido
  en los archivos Parquet. El consumidor lo recibe sin ambigüedad.

---

## 3. PySpark / Spark

### Spark
Motor de procesamiento distribuido (Java/Scala por dentro). Reparte el trabajo en N workers.

### PySpark
API Python para hablarle a Spark. Lo que usamos en Glue Jobs y en dev local.
Convención universal de imports: `from pyspark.sql import functions as F`. El alias `F`
está en los docs oficiales de Spark — lo silenciamos en ruff con `# noqa: N812`.

### Java requirement (PySpark local)
PySpark necesita **Java 11+** en runtime: el Python solo arma comandos, la ejecución real
corre en una JVM. En este proyecto, los tests de Spark hacen un preflight (`shutil.which("java")`
+ `JAVA_HOME`) y **skipean limpio** si Java no está. Marianela puede instalarlo si quiere
correr los tests locales de transformación; sino, valida directo en el smoke test de Glue
(sub-paso C de cada transformación).

### `SparkSession` y `SparkSession.builder`
Punto de entrada a Spark. Una SparkSession por proceso. Pattern:
```python
spark = (SparkSession.builder.appName("...").master("local[2]").getOrCreate())
```
En tests locales usamos `master("local[2]")` (2 workers en el mismo proceso). En Glue Job
real la sesión la levanta el wrapper de AWS, no nosotros.

### Spark DataFrame
Estructura tipo tabla distribuida en memoria de Spark. API tipo SQL: `.where()`,
`.groupBy()`, `.join()`, `.write.parquet(...)`.

Analogía Qlik: tabla residente en RAM durante un reload, sobre la que aplicás operaciones
declarativas.

### Partition pruning (Spark)
Cuando hacés `.where(F.col("ingested_at") > hwm)` sobre datos particionados Hive-style, Spark
**no lee** los archivos de las particiones que no satisfacen el filtro. Esa es la magia que
hace que incremental loads sean baratos.

### `coalesce` / `repartition`
Operaciones que controlan cuántos archivos Spark va a escribir. `coalesce(N)` baja el número
de particiones (sin shuffle); `repartition(N)` lo cambia (con shuffle). En staging típicamente
hacemos `coalesce(1)` por partición para que no queden 200 archivitos chicos.

### Dynamic partition overwrite
Config de Spark: `spark.sql.sources.partitionOverwriteMode = "dynamic"`. Cuando hacés
`df.write.mode("overwrite").partitionBy(...)`, controla qué se borra:
- **`static`** (default): borra TODA la tabla y reescribe solo lo que tenés en el batch.
  **Catastrófico para incremental**: si tu batch solo trae marzo, te perdés enero/febrero.
- **`dynamic`**: borra SOLO las particiones presentes en el batch. Las que no tocás,
  intactas. Esto es lo que queremos.

Se setea en el wrapper del Glue Job: `spark.conf.set("spark.sql.sources.partitionOverwriteMode", "dynamic")`.

---

## 4. Testing y dev local

### moto
Librería Python que **mockea AWS** localmente. Tests con `@mock_aws` interceptan llamadas a
boto3 y simulan AWS sin red ni costo. Nos permite testear código que usa S3 sin gastar nada.

### pytest markers
Etiquetas en los tests para filtrarlos:
- `@pytest.mark.unit`: sin IO, sin AWS. Corren rápido.
- `@pytest.mark.integration`: con AWS mockeado (moto).
- `@pytest.mark.slow`: tests que tardan más de 1s.

### pytest session-scoped fixtures
Fixtures con `scope="session"` se instancian **una sola vez por corrida de pytest** y se
reusan entre todos los tests. Usado para recursos caros de levantar (ej: la SparkSession,
que tarda ~10s de cold start). El opuesto es `scope="function"` (default), que instancia
una vez por test.

### `pytest.importorskip(...)`
Función pytest que **skipea el módulo completo** si el package indicado no está instalado.
Lo usamos en `test_staging_orders.py` para que el archivo no falle de collection cuando
pyspark no está. Se llama ANTES de cualquier import dependiente.

### pydantic-settings
Librería que carga environment variables tipadas (desde `.env` y `os.environ`) a un objeto
`Settings` validado. Si el `.env` está mal formado, falla al arrancar con un mensaje claro.

### structlog
Librería de logging "estructurado": cada log es un dict de `key=value` en vez de un string
libre. Logs JSON en producción (Lambda), output legible en dev local.

---

## 5. Convenciones del proyecto

### `.env` y `.env.example`
- `.env.example`: plantilla committeada con placeholders. Vive en git.
- `.env`: tu copia real con credenciales y valores propios. **Gitignored.** Nunca se commitea.

### ADR (Architecture Decision Record)
Documento corto en `docs/adr/` que justifica una decisión arquitectónica importante.
Append-only: nunca se editan, se supersedean. Slash command `/adr` para crear uno nuevo.

### Las 5 capas de `src/olist_pipeline/`
| Capa | Rol | Puede importar |
|---|---|---|
| `core/` | Cross-cutting: config, logging, AWS factories. | stdlib + boto3 + pydantic + structlog |
| `ingestion/` | Kaggle → S3 raw. | `core/` |
| `transformation/` | Glue Jobs PySpark + Athena SQL. | `core/` |
| `quality/` | Validaciones, quarantine. | `core/`, `transformation/` (read-only) |
| `orchestration/` | Lambdas + EventBridge rules. | todo |

Un hook bloquea crear archivos `.py` fuera de estas 5 carpetas o `tests/`.

### `infra/`
Scripts bash + JSON que provisionan recursos AWS. **No** es IaC formal (Terraform/CDK), pero
es reproducible. Cada script:
- Es idempotente (si el recurso existe, skip + re-asserción).
- Lee `.env` (no hardcodea valores).
- Aplica las 3 tags obligatorias.

### Friday teardown
Cada viernes corres `infra/destroy-all.sh` (cuando exista) para apagar Crawlers/Jobs/Lambdas.
NO se borran buckets (datos) ni roles (gratis). El lunes los recreás con `bring-up.sh`.
Defensa contra el "olvidé esto encendido el fin de semana → factura sorpresa". Como en este
proyecto elegimos tracking manual de costos en vez de budget alerts, este reflex importa más.

---

## 6. Herramientas / CLI

### `uv`
Package manager Python rápido (Rust). Reemplaza pip + virtualenv + pip-tools.
Comandos clave: `uv sync` (instala deps), `uv run <cmd>` (corre algo en el venv).

### `ruff`
Linter + formatter Python rápido (Rust). Reemplaza black + isort + flake8 + pyupgrade.
Configurado en `pyproject.toml`. Un hook lo corre auto en cada edit de `.py`.

### `pyright`
Type checker estricto. Configurado en strict mode sobre `src/` y `tests/`.

### `pytest`
Framework de tests. Configurado con los marcadores `unit`/`integration`/`slow`.

### `envsubst`
Herramienta de línea de comandos que reemplaza `${VAR}` por valores de env. La usamos en
`create-glue-role.sh` para sustituir `${S3_BUCKET_RAW}` en el JSON template del policy antes
de aplicarlo. Viene con Git for Windows.

### Kaggle API
Servicio HTTP de Kaggle para descargar datasets. Auth con token único (`KAGGLE_API_TOKEN`,
prefijo `KGAT_`) — el formato viejo `KAGGLE_USERNAME` + `KAGGLE_KEY` está deprecado.

---

## 7. Git / control de versiones

> Modelo mental: pensá en `main` como **la versión publicada** del proyecto, y en una
> **branch** como **un borrador aparte** donde trabajás sin tocar lo publicado. El **PR**
> es el pedido formal de "publicar el borrador", y el **merge** es el acto de publicarlo.

### Commit
Una "foto" guardada de tus cambios, con un mensaje que explica qué hiciste. Es la unidad
mínima de la historia. Cada commit tiene un hash (ej: `30146b3`) que lo identifica.

### Branch (rama)
Una línea de desarrollo paralela. Partís de `main`, creás una rama (ej:
`feat/athena-staging-query`), y commiteás ahí sin afectar `main`. Si algo sale mal, `main`
queda intacto. Cuando el trabajo está listo, lo integrás de vuelta a `main` (merge).

`main` es la rama principal (la "oficial"). Trabajar siempre en ramas y no commitear directo
a `main` es la práctica estándar: mantiene lo publicado siempre en estado revisable.

### Remote / `origin` / push
- **Remote**: una copia del repo en un servidor (acá, GitHub). El remote default se llama
  **`origin`**.
- **`push`**: subir tus commits locales al remote. Hasta que no hacés `push`, tu trabajo vive
  solo en tu máquina.

### Pull Request (PR)
Una **solicitud de incorporación**: le pedís a GitHub "quiero meter los commits de esta rama
dentro de `main`". El PR es el **punto de revisión** — muestra el diff completo (qué líneas
cambian), corre los checks automáticos si los hay, y permite comentar antes de integrar.

Analogía neutral: como mandar un documento con "control de cambios" a aprobación antes de que
entre en la versión maestra. En un equipo, otra persona lo revisa; trabajando sola (este
proyecto), te lo aprobás vos misma, pero el PR igual deja registro de qué entró y por qué.

### Merge (fusión)
El acto de **integrar** los commits de la rama en `main`. Cierra el PR. Tres formas:
- **Merge commit** (default): trae todos los commits de la rama y agrega un commit de fusión.
  Preserva la historia completa (útil cuando los commits son significativos).
- **Squash**: aplasta todos los commits de la rama en **uno solo** sobre `main`. Historia
  lineal y limpia (útil cuando la rama tiene muchos commits chiquitos de "wip").
- **Rebase**: reaplica los commits sobre `main` sin commit de fusión.

### Pull (`git pull`)
Bajar a tu copia local los cambios que hay en el remote. Después de mergear un PR en GitHub,
hacés `git checkout main && git pull` para que tu `main` local quede al día.
