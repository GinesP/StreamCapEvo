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

#### 3. `get_ui_state(recording, now=None)`

Pendiente de evaluación. Debe ofrecer a la UI una vista consistente para evitar llamadas dispersas o lógica duplicada.

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

**Siguiente candidato recomendado**: `app/qt/components/recording_card.py`

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

Cuando los consumidores ya usen Precog:

- dejar `HistoryManager` como dependencia interna,
- reducir nuevos accesos directos desde UI o manager,
- evaluar siguientes limpiezas sin cambiar comportamiento.

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
- [ ] Evaluar limpieza posterior una vez centralizado (incluye absorber `_get_forecast_time_info`)

## Punto de reentrada para futuras sesiones

Si retomamos este trabajo en otra sesión, el siguiente paso recomendado es:

1. evaluar si Precog necesita un método `time_state()` o similar para absorber `_get_forecast_time_info()` de `live_forecast_dialog.py` sin que la UI duplique lógica de clustering,
2. solo entonces eliminar el import residual de `HistoryManager` en `live_forecast_dialog.py`,
3. revisar si queda algún consumidor directo de `HistoryManager` fuera de Precog y del diálogo residual.

## Referencias

- `docs/INTELLIGENCE_ES.md`
- `app/core/recording/history_manager.py`
- `app/core/recording/record_manager.py`
- `app/models/recording/recording_model.py`
- `app/core/recording/predictor_metrics.py`
- `app/core/recording/precog.py`
- `tests/test_precog.py`
