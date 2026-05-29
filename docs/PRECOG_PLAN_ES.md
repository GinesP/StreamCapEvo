# Plan de Precog

Este documento deja por escrito qué ya decidimos, qué ya se hizo y cuál es el siguiente camino para centralizar la inteligencia/predicción sin cambiar el comportamiento actual más de lo necesario.

## Decisión actual

- El nuevo punto único del sistema se llamará **Precog**.
- **No** vamos a reescribir el algoritmo ahora.
- **No** vamos a hacer sobreingeniería.
- El objetivo inmediato es **ordenar** el sistema para que futuros cambios se hagan desde un único sitio.

## Reglas de trabajo acordadas

1. Cambiar lo mínimo posible el funcionamiento actual.
2. Evitar sobreingeniería: métodos sencillos, pocos puntos de entrada, organización clara.
3. Reducir la superficie de cambio: que una modificación futura no obligue a tocar muchos archivos.
4. Si durante el trabajo aparece una mejora que se aparta de estas reglas, **hay que preguntarla primero**.

## Qué se hizo ya

### 1. Auditoría inicial del sistema de inteligencia

Se confirmó que la lógica actual está repartida entre varias piezas:

- `app/models/recording/recording_model.py`
  - Guarda y muta datos como `historical_intervals` y `live_sessions`.
- `app/core/recording/history_manager.py`
  - Calcula likelihood, forecast details y adjusted interval.
- `app/core/recording/record_manager.py`
  - Decide dispatch, prioridad de cola y ejecución operativa.
- UI Qt
  - Consume predicción desde varios puntos, con riesgo de lógica derivada duplicada.

### 2. Conclusión arquitectónica

Se decidió crear **Precog** como fachada única del sistema predictivo.

Precog debe centralizar:

- lectura del estado predictivo de un stream,
- decisión operativa mínima (cola / intervalo / check),
- exposición consistente de datos para UI.

### 3. Métricas del predictor

Se revisó `predictor_metrics` y se concluyó que:

- su propósito es **tuning reciente** del algoritmo,
- no hace falta conservar histórico indefinido,
- la ventana útil actual es de **72 horas**.

### 4. Cambio ya implementado

Ya está implementada la retención automática de 72 horas para `predictor_metrics`.

Archivos afectados:

- `app/core/recording/predictor_metrics.py`
- `test_predictor_metrics.py`
- `docs/INTELLIGENCE_ES.md`

## Diseño acordado para Precog v1

### Objetivo

Precog v1 será una **fachada simple** sobre el comportamiento actual.

No reemplaza todavía el algoritmo interno. Solo lo reúne en un punto único.

### Archivo nuevo previsto

- `app/core/recording/precog.py` ✅ creado

### Clase pública prevista

- `Precog` ✅ creada

### Responsabilidades públicas previstas

#### 1. `predict(recording, now=None)`

Debe devolver un snapshot unificado con datos como:

- `likelihood`
- `confidence`
- `priority_score`
- `consistency_score`
- `adjusted_interval`
- `forecast_details`

**Estado actual**: ✅ implementado como primer paso mínimo.

Detalles del paso ya hecho:

- `Precog.predict()` delega en `HistoryManager.get_forecast_details()`.
- `Precog.predict()` delega en `HistoryManager.get_adjusted_interval()`.
- Devuelve un `PrecogPrediction` simple e inmutable.
- No cambia el comportamiento existente ni migra todavía consumidores.

#### 2. `decide_queue(recording, base_interval, now=None)`

**Estado**: ✅ implementado.

Encapsula la decisión operativa mínima actual:

- `should_check`
- `queue_priority` (`F`, `M`, `S`)
- `adjusted_interval`
- `likelihood`
- `reason`

Detalles del paso:

- `Precog.decide_queue()` delega en `HistoryManager.get_forecast_details()` y `HistoryManager.get_adjusted_interval()`.
- Conserva el cap de favoritos (`>180 → 180`) exactamente como en `record_manager.py`.
- Conserva los thresholds de cola (`<=60` F, `<=180` M, else S).
- Calcula `should_check` replicando la lógica de `utils.is_time_interval_exceeded` para mantener testabilidad.
- `record_manager.py` ahora consume `Precog.decide_queue()` en lugar de calcular `likelihood`, `adjusted_interval`, `queue_key` y `should_check` inline.

#### 3. `time_state(recording, now=None)`

**Estado**: ✅ implementado.

Centraliza en Precog el cálculo de estado temporal que antes vivía duplicado en `_get_forecast_time_info()` de `live_forecast_dialog.py`.

- `Precog.time_state()` replica fielmente la lógica de clustering y estados (`none`, `live_range`, `expected`, `delayed`, `countdown`, `upcoming`).
- Incluye helper privado `Precog._cluster_hours()` para eliminar la dependencia residual a `HistoryManager._cluster_hours()` desde la UI.
- `_get_forecast_time_info()` en `live_forecast_dialog.py` ahora es un wrapper delegado a `Precog.time_state()`.
- El import de `HistoryManager` se eliminó de `live_forecast_dialog.py`.

## Qué NO vamos a hacer en esta fase

- Reescribir `HistoryManager`
- Rediseñar fórmulas de scoring
- Cambiar precedencias de comportamiento entre histórico y sesiones
- Mover todavía la persistencia de `Recording`
- Reorganizar workers, colas o semáforos
- Introducir capas extra sin necesidad real

## Plan de migración

## Paso 1 — Crear Precog

Crear `app/core/recording/precog.py` con una clase `Precog` mínima.

Objetivo:

- centralizar lectura,
- no cambiar comportamiento,
- delegar internamente en la lógica existente.

**Estado**: ✅ completado.

Archivos creados en este paso:

- `app/core/recording/precog.py`
- `tests/test_precog.py`

Verificación ejecutada:

- `python -m unittest tests.test_precog -v` → OK

## Paso 2 — Migrar consumidores de lectura de bajo riesgo

Mover primero los consumidores que solo leen datos predictivos:

- `app/qt/components/recording_info_dialog.py` ✅ migrado
- `app/qt/components/recording_card.py` ✅ migrado
- `app/qt/views/recordings_view.py` ✅ migrado

Objetivo:

- reducir acceso directo a `HistoryManager`,
- comprobar que Precog sirve como punto de entrada estable.

**Resultado real tras la migración**: los tres consumidores de lectura de bajo riesgo ya quedaron migrados y este paso puede considerarse cerrado.

## Paso 3 — Migrar `live_forecast_dialog.py`

Revisado y migrado parcialmente:

- `app/qt/components/live_forecast_dialog.py`

Este archivo tiene lógica derivada/duplicada (`_get_forecast_time_info`) que usa `HistoryManager._cluster_hours`. No se migró esa parte porque requeriría absorber la lógica de clustering en Precog o rehacer el estado de UI, lo que excede el cambio mínimo seguro acordado.

### Qué se migró
- `HistoryManager.get_forecast_details()` → `Precog.predict(...).forecast_details` (2 usos en `ForecastItemWidget.update_time_info` y `_slot_minutes_until`).
- `HistoryManager.get_likelihood_score()` → `Precog.predict(...).likelihood` (1 uso en `_populate_list`).

### Qué NO se migró y por qué
- `HistoryManager._cluster_hours(active_hours)` dentro de `_get_forecast_time_info()`. Es un método privado de `HistoryManager`; `Precog` no lo expone. Migrarlo requeriría o bien añadirlo a Precog (sobreingeniería) o reescribir la máquina de estados del diálogo (cambio de comportamiento). Se deja pendiente para una fase posterior de consolidación.

### Estado del import
- El archivo aún importa `HistoryManager` por `_cluster_hours`. No se puede eliminar hasta que `_get_forecast_time_info()` se absorba en Precog o se reescriba.

## Paso 4 — Mover la decisión de cola a Precog

**Estado**: ✅ completado.

Integrar Precog en:

- `app/core/recording/record_manager.py`

Objetivo:

- que la decisión `likelihood -> adjusted_interval -> queue` quede centralizada.

Archivos afectados:

- `app/core/recording/precog.py` — añadidos `PrecogDecision`, `Precog.decide_queue()`, `Precog._should_check()`
- `app/core/recording/record_manager.py` — reemplazado bloque inline de decisión por llamada a `Precog.decide_queue()`
- `tests/test_precog.py` — añadidos tests focalizados para `decide_queue`

Verificación ejecutada:

- `python -m unittest tests.test_precog -v` → OK (13 tests)
- `python -m unittest discover` → OK (errores preexistentes por dependencias Qt/aiofiles no instaladas)

## Paso 5 — Consolidación

**Estado**: 🟡 en progreso.

Cuando los consumidores ya usen Precog:

- dejar `HistoryManager` como dependencia interna,
- reducir nuevos accesos directos desde UI o manager,
- evaluar siguientes limpiezas sin cambiar comportamiento.

### Consolidación aplicada en Precog v1.1

Se detectó que todavía sobrevivía una duplicación de regla de negocio fuera de Precog:

- la traducción de `interval_seconds -> queue key (F/M/S)` seguía reimplementada en UI.

Para cerrar esa grieta sin cambiar semántica se hizo un ajuste mínimo:

- `Precog.interval_to_queue_key(interval_seconds)` pasa a ser la regla canónica,
- `Precog.decide_queue()` delega en ese helper,
- `recording_card.py` y `recordings_view.py` dejan de reconstruir la cola con `if/elif` inline y consumen la regla centralizada.

Archivos afectados en esta consolidación:

- `app/core/recording/precog.py`
- `app/qt/components/recording_card.py`
- `app/qt/views/recordings_view.py`

Verificación ejecutada:

- `python -m unittest tests.test_precog -v` → OK (20 tests)

## Paso 6 — Snapshot unificado de Precog

**Estado**: ⏳ pendiente de diseño/implementación.

La siguiente evolución alineada con `PRECOG_EXPLORATION_ES.md` no es seguir sumando helpers sueltos, sino introducir un snapshot canónico que reúna en una sola foto coherente:

- predicción,
- decisión operativa,
- estado consumible por UI.

### Propuesta mínima actual

Crear un `PrecogSnapshot` y un nuevo punto de entrada:

- `Precog.snapshot(recording, now=None) -> PrecogSnapshot`

Campos iniciales previstos para el snapshot:

- `likelihood`
- `confidence`
- `forecast_details`
- `reason_key`
- `adjusted_interval`
- `queue_key`
- `should_check`
- `time_state`
- `is_stale`
- `priority_score`
- `consistency_score`

### Objetivo de esta fase

- dejar una sola fuente de verdad por ciclo,
- reducir recomputación y diferencias entre manager/UI,
- preparar el camino para futuras notificaciones de cambios hacia UI,
- mantener compatibilidad con `predict()`, `decide_queue()` y `time_state()` como wrappers o helpers derivados.

### Checklist de Precog v1.2

- [ ] Definir el `dataclass PrecogSnapshot` con el shape mínimo acordado
- [ ] Implementar `Precog.snapshot(recording, now=None)` reutilizando la lógica actual
- [ ] Mantener `Precog.predict()`, `Precog.decide_queue()` y `Precog.time_state()` compatibles durante la transición
- [ ] Migrar un consumidor chico para validar el enfoque (`recording_card.py` o `recordings_view.py`)
- [ ] Evaluar si `record_manager.py` puede leer parte de la decisión desde el snapshot sin cambiar comportamiento
- [ ] Documentar claramente qué campos del snapshot son semántica de negocio y cuáles siguen siendo presentación
- [ ] Dejar anotado el nuevo punto de reentrada tras esa fase

## Estado actual

- [x] Detectado el problema de dispersión de la inteligencia
- [x] Decidido el nombre **Precog**
- [x] Acordadas las reglas de diseño
- [x] Resuelta la retención de 72 horas de `predictor_metrics`
- [x] Crear `app/core/recording/precog.py`
- [x] Crear `Precog.predict()` como fachada mínima
- [x] Añadir tests focalizados de equivalencia inicial (`tests/test_precog.py`)
- [x] Migrar consumidor de lectura de bajo riesgo a Precog (`recording_info_dialog.py`)
- [x] Migrar `recording_card.py` a Precog
- [x] Migrar resto de consumidores de lectura a Precog (`recordings_view.py`)
- [x] Migrar `live_forecast_dialog.py` parcialmente (lecturas directas seguras)
- [x] Migrar decisión operativa de cola a Precog
- [x] Implementar `Precog.time_state()` y absorber `_get_forecast_time_info()`
- [x] Eliminar import residual de `HistoryManager` en `live_forecast_dialog.py`
- [x] Centralizar la regla `interval -> queue key` en Precog
- [x] Eliminar duplicación de la cola `F/M/S` en UI principal
- [ ] Evaluar limpieza posterior una vez centralizado
- [ ] Diseñar e introducir `PrecogSnapshot` como snapshot unificado

## Punto de reentrada para futuras sesiones

Si retomamos este trabajo en otra sesión, el siguiente paso recomendado es:

1. definir el shape mínimo de `PrecogSnapshot`,
2. implementarlo sin romper la API actual,
3. migrar un consumidor pequeño para validar el enfoque,
4. después evaluar si conviene avanzar hacia notificaciones de cambios Precog → UI.

## Referencias

- `docs/INTELLIGENCE_ES.md`
- `app/core/recording/history_manager.py`
- `app/core/recording/record_manager.py`
- `app/models/recording/recording_model.py`
- `app/core/recording/predictor_metrics.py`
- `app/core/recording/precog.py`
- `tests/test_precog.py`
