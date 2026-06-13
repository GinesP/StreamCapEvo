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
- `Precog.time_state()` delega en `HistoryManager._cluster_info()` directamente; no se introdujo un helper privado en Precog porque la UI principal ya no consume clustering (solo `live_forecast_dialog.py` lo hace indirectamente a través de `time_state`).
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

**Estado**: ✅ completado.

`app/qt/components/live_forecast_dialog.py` quedó consolidado sobre `Precog.snapshot()` como consumidor de UI de mayor valor pendiente.

### Resultado real

- `ForecastItemWidget.update_time_info()` ya no combina `Precog.time_state()` + `Precog.predict()`; ahora reutiliza `snapshot.time_state` y `snapshot.forecast_details`.
- `_populate_list()` ya no recalcula `Precog.predict()` ni `Precog.time_state()` por separado para score, filtro y render.
- `_slot_minutes_until()` ahora lee `snapshot.forecast_details["next_slot_text"]` y `snapshot.time_state` desde la misma foto coherente del recording.
- Se eliminó el wrapper residual `_get_forecast_time_info()` porque dejó de aportar valor.

### Impacto

- Se reduce recomputación duplicada en un diálogo que antes era el consumidor UI más pesado de Precog.
- Cada recording usa una sola muestra coherente de estado predictivo al poblar el diálogo.
- No cambió el comportamiento funcional esperado: el filtrado, el orden por proximidad y el render siguen basándose en los mismos datos, ahora reunidos en `PrecogSnapshot`.

### Archivos afectados

- `app/qt/components/live_forecast_dialog.py`

### Verificación ejecutada

- `python -m unittest discover` → OK (129 tests)

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

**Estado**: 🟡 casi cerrado.

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

### Pendiente puntual para cerrar esta fase

Quedó un único pendiente explícito de consolidación:

- [x] Evaluar limpieza posterior una vez centralizado

Eso implica revisar si, después de las migraciones ya hechas, conviene:

- eliminar imports o helpers residuales,
- reducir accesos directos que ya no aportan valor,
- dejar más claro qué consumidores deberían pasar por `snapshot()` y cuáles pueden seguir con wrappers livianos.

No es un blocker funcional. Es una auditoría de limpieza y cierre.

## Paso 6 — Snapshot unificado de Precog

**Estado**: ✅ implementado.

La siguiente evolución alineada con `PRECOG_EXPLORATION_ES.md` no es seguir sumando helpers sueltos, sino introducir un snapshot canónico que reúna en una sola foto coherente:

- predicción,
- decisión operativa,
- estado consumible por UI.

### Implementación mínima aplicada

Crear un `PrecogSnapshot` y un nuevo punto de entrada:

- `Precog.snapshot(recording, now=None) -> PrecogSnapshot`

Campos actuales del snapshot:

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

### Resultado real de la implementación

Se implementó `Precog.snapshot(recording, now=None)` como una composición conservadora de la API actual:

- `Precog.predict()` aporta `likelihood`, `confidence`, `forecast_details`, `priority_score` y `consistency_score`.
- `Precog.decide_queue()` aporta `adjusted_interval`, `queue_key`, `should_check` y `reason`.
- `Precog.time_state()` aporta `time_state`.
- `RecordingStateLogic.is_stale()` aporta `is_stale`.

Esto permite introducir una foto canónica por ciclo sin reescribir todavía la lógica interna ni romper consumidores existentes.

### Semántica de negocio vs presentación

Campos principalmente de **semántica de negocio/operación**:

- `likelihood`
- `confidence`
- `forecast_details`
- `reason_key`
- `adjusted_interval`
- `queue_key`
- `should_check`
- `is_stale`
- `priority_score`
- `consistency_score`

Campos principalmente **orientados al consumo de UI/presentación**:

- `time_state`

Nota: `forecast_details` sigue mezclando datos predictivos con algunos campos pensados para mostrar ventana/slot en UI. En esta fase NO se separó más para no cambiar comportamiento.

### Checklist de Precog v1.2

- [x] Definir el `dataclass PrecogSnapshot` con el shape mínimo acordado
- [x] Implementar `Precog.snapshot(recording, now=None)` reutilizando la lógica actual
- [x] Mantener `Precog.predict()`, `Precog.decide_queue()` y `Precog.time_state()` compatibles durante la transición
- [x] Migrar un consumidor chico para validar el enfoque (`recording_card.py`)
- [x] Evaluar si `record_manager.py` puede leer parte de la decisión desde el snapshot sin cambiar comportamiento
- [x] Documentar claramente qué campos del snapshot son semántica de negocio y cuáles siguen siendo presentación
- [x] Dejar anotado el nuevo punto de reentrada tras esa fase

### Archivos afectados en Precog v1.2

- `app/core/recording/precog.py`
- `app/qt/components/recording_card.py`
- `tests/test_precog.py`
- `tests/test_recording_card_badge.py`

### Verificación ejecutada

- `python -m unittest tests.test_precog` → OK
- `python -m unittest discover` → OK en tests del proyecto; persisten errores de entorno ya conocidos por dependencias faltantes (`aiofiles`, `qasync`)

## Paso 7 — Migrar decisión operativa de `record_manager.py` a `Precog.snapshot()`

**Estado**: ✅ completado.

`record_manager.py` ya no llama a `Precog.decide_queue()` directamente desde `check_all_live_status`. En su lugar lee del snapshot unificado:

- `Precog.snapshot(recording, now=None)` es el nuevo punto de entrada.
- Ajusta `recording.loop_time_seconds = base_interval` antes del snapshot para que el cómputo interno de `adjusted_interval` use la misma base de siempre (proveniente de configuración de usuario).
- Lee `snap.adjusted_interval`, `snap.likelihood`, `snap.should_check`, `snap.queue_key` — exactamente los mismos campos que antes venían de `PrecogDecision`.

Archivos afectados:

- `app/core/recording/record_manager.py` — el bloque de decisión ahora consume snapshot
- `tests/test_precog.py` — tests de contrato que prueban equivalencia snapshot ↔ decide_queue con `recording.loop_time_seconds = base_interval`
- `tests/test_record_manager_precog.py` — tests de integración que verifican que `check_all_live_status` lee de snapshot

Verificación ejecutada:

- `python -m unittest tests.test_precog` → OK
- `python -m unittest tests.test_record_manager_precog` → OK
- `python -m unittest discover` → OK (tests del proyecto; persisten errores de entorno conocidos)

## Paso 8 — Migrar `recordings_view.py` a `Precog.snapshot()` + cerrar limpieza post-migración

**Estado**: ✅ completado.

`RecordingListDelegate` en `recordings_view.py` ahora consume el snapshot unificado:

- `Precog.snapshot(rec)` reemplaza a las tres llamadas separadas:
  - `Precog.predict(rec).likelihood` → `snap.likelihood`
  - `Precog.interval_to_queue_key(interval)` + acceso a `QUEUE_COLORS` → `snap.queue_key` + lookup inline
  - `RecordingStateLogic.is_stale(rec)` → `snap.is_stale`
- El nuevo helper `_snapshot_data()` devuelve `(queue_key, queue_color, likelihood, is_stale)` desde un solo snapshot, con manejo de errores por si falla.
- Se eliminan los métodos `_queue_badge()` y `_likelihood()` que ahora son redundantes.
- Se actualiza `test_recordings_view_precog.py` para probar `_snapshot_data()` contra `Precog.snapshot`.

### Limpieza post-migración (auditoría)

Se verificó que no quedan accesos directos relevantes a `HistoryManager` desde UI en los consumidores principales de Precog.

Consumidores actuales:
- ✅ `record_manager.py` — snapshot
- ✅ `recording_card.py` — snapshot
- ✅ `recordings_view.py` — snapshot
- ✅ `live_forecast_dialog.py` — snapshot
- ✅ `recording_info_dialog.py` — forecast (liviano, diálogo bajo demanda)

### Archivos afectados en Paso 8

- `app/qt/views/recordings_view.py` — migrado a snapshot, eliminados `_queue_badge` y `_likelihood`
- `tests/test_recordings_view_precog.py` — tests actualizados para `_snapshot_data`
- `docs/PRECOG_PLAN_ES.md` — este documento actualizado

### Verificación ejecutada

- `python -m unittest tests.test_precog tests.test_recordings_view_precog tests.test_recording_card_badge` → OK

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
- [x] Evaluar limpieza posterior una vez centralizado
- [x] Diseñar e introducir `PrecogSnapshot` como snapshot unificado
- [x] Migrar `record_manager.py` a snapshot unificado
- [x] Migrar `recordings_view.py` a `Precog.snapshot()`
- [x] Cerrar limpieza post-migración (auditoría de accesos directos a `HistoryManager` desde UI)
- [x] Optimizar recomputación interna en `Precog.snapshot()` (Paso 9)

## Qué ya quedó hecho en el código

Además del checklist anterior, hoy el estado real del repo ya confirma esto:

- `Precog v1.2` quedó implementado, probado y consolidado como base actual.
- `app/core/recording/precog.py` ya actúa como fachada del núcleo predictivo.
- `record_manager.py` ya consume `Precog.snapshot()` como punto de entrada operativo principal.
- `recording_card.py` ya consume snapshot unificado.
- `recordings_view.py` ya consume `Precog.snapshot()` a través de una cache de badges que evita computar `Precog.snapshot()` en el hot path de `paint()`, con el queue key proveniente de `Precog.stable_queue_key()` para evitar jitter en la UI.
- `recording_info_dialog.py` ya consume `Precog.forecast()` (camino liviano, solo forecast_details sin cómputo de adjusted_interval).
- `live_forecast_dialog.py` ya consume `Precog.snapshot()` como fuente única para likelihood, estado temporal, forecast y orden por proximidad.
- Se añadió `Precog.stable_queue_key(recording)` que devuelve un queue key basado en el intervalo base configurado (sin jitter), con fallback a 60 segundos (legacy UI) cuando `loop_time_seconds` es `None`. Esto restaura la semántica del viejo `_queue_badge()`.
- El hot path de `paint()` en `RecordingsView` ahora lee de `model._badge_cache` en lugar de llamar `Precog.snapshot()`. La cache se precarga desde el timer de 1 segundo (`_on_refresh_tick`).

## Qué ya no queda pendiente (cerrado en este bloque)

1. ✅ **Migrar `recordings_view.py` a `Precog.snapshot()`**
   - `RecordingListDelegate._snapshot_data()` reemplazó a `_queue_badge()` y `_likelihood()`,
   - consume snapshot unificado por streaming, reduciendo de 3 llamadas separadas a 1,
   - sigue exactamente el mismo patrón establecido por `recording_card.py`,
   - `test_recordings_view_precog.py` actualizado para probar `_snapshot_data()` contra `Precog.snapshot`.

2. ✅ **Cerrar la limpieza post-migración (auditoría)**
   - Se verificó que no quedan accesos directos relevantes a `HistoryManager` desde UI.
   - `recording_info_dialog.py` podría refinarse en una fase posterior, pero su impacto es bajo por ser un diálogo bajo demanda.
   - `live_forecast_dialog.py` ya quedó consolidado sobre `Precog.snapshot()` sin ampliar superficie pública innecesaria.

## Qué sigue pendiente

Pendientes reales, ordenados por prioridad para retomar sin perder contexto:

1. **Evaluar si la consolidación UI de Precog ya está cerrada**
   - `recording_card.py`, `recordings_view.py`, `live_forecast_dialog.py` y `recording_info_dialog.py` ya consumen Precog,
   - cada uno usa el método justo para su necesidad: `snapshot()` los pesados, `forecast()` el liviano,
   - no quedan consumidores UI sin migrar.

2. **Baja prioridad: documentar cierre formal del tramo de consolidación de consumidores UI**
   - si no aparece otro consumidor relevante,
   - el siguiente trabajo valioso ya deja de ser migración de lectores y pasa a mejoras posteriores sobre la API de Precog.

## Cerrado en esta auditoría

1. ✅ **Queue badge semantics restauradas**: el badge de cola ahora usa `Precog.stable_queue_key()`, basado en el intervalo base configurado sin jitter, con default 60 segundos (legacy). Esto elimina el flicker causado por `adjusted_interval` (jitter) que `Precog.snapshot()` propagaba indirectamente.
2. ✅ **Heavy snapshot fuera de `paint()`**: `RecordingListDelegate.paint()` lee de `model._badge_cache`, precargada desde el timer de 1 segundo. El fallback existe por si la cache está vacía, pero usa `stable_queue_key` (ligero) más `Precog.snapshot()` (pesado solo en el fallback).
3. ✅ **Default fallback corregido**: el valor legacy de 60 para `loop_time_seconds=None` está restaurado en el path de badge. El path operativo (`Precog.DEFAULT_BASE_INTERVAL=300`) no cambió — la diferencia es intencional porque badge y operación tienen necesidades distintas.
4. ✅ **Docs actualizados**: se corrigieron afirmaciones que daban por equivalentes paths que no lo eran, y se documentó la decisión de `stable_queue_key`.
5. ✅ **Tests fortalecidos**: se añadieron tests para `stable_queue_key`, tests de verificación de semántica (cache vs snapshot, default 60), y tests de `_badge_data()` que verifican que la cache evita llamadas a `Precog.snapshot()`.

## Paso 9 — Optimizar recomputación interna en Precog.snapshot()

**Estado**: ✅ completado.

### Problema

`Precog.snapshot()` llamaba a `Precog.predict()` y `Precog.decide_queue()`. Cada uno de esos métodos llamaba independientemente a `HistoryManager.get_forecast_details()` y `HistoryManager.get_adjusted_interval()` (que a su vez llama internamente a `get_likelihood_score` → `get_forecast_details`).

Esto producía por cada snapshot:

- **4 llamadas** a `get_forecast_details()` (2 de predict + 2 de decide_queue)
- **2 llamadas** a `get_adjusted_interval()`

### Solución aplicada

`snapshot()` ahora computa los valores centrales directamente sin delegar en `predict()` ni `decide_queue()`:

- Llama `get_forecast_details()` **una vez explícitamente** (más una llamada implícita dentro de `get_adjusted_interval()` → `get_likelihood_score()`, total **2** por snapshot; antes: **4**)
- Llama `get_adjusted_interval()` una sola vez (antes: **2**)
- Aplica el cap de favoritos inline
- Calcula `queue_key` y `should_check` inline

### Reducción de trabajo duplicado

| Medición | Antes | Después |
|---|---|---|
| `get_forecast_details()` por snapshot | 4 | 2 |
| `get_adjusted_interval()` por snapshot | 2 | 1 |
| Dependencia de `predict()`/`decide_queue()` | sí | no |

#### Nota histórica: desajuste temporal ya resuelto

Durante este paso quedó identificada una deuda preexistente: `snapshot(now=...)` computaba el forecast con el `now` del caller, pero `get_adjusted_interval()` derivaba el intervalo a través de `get_likelihood_score()` → `get_forecast_details(recording)` **sin pasar `now`**, por lo que usaba `datetime.now()` internamente.

Esa inconsistencia quedó **cerrada en un bloque posterior** propagando `now` en toda la cadena:

- `Precog.predict(..., now=...)`
- `Precog.snapshot(..., now=...)`
- `Precog.decide_queue(..., now=...)`
- `HistoryManager.get_adjusted_interval(..., now=...)`
- `HistoryManager.get_likelihood_score(..., now=...)`

Con eso, forecast e intervalo ajustado vuelven a quedar congelados sobre el mismo instante temporal cuando el caller provee `now` explícito.

`predict()` y `decide_queue()` se mantienen públicos e inalterados para los consumidores existentes (`live_forecast_dialog.py`, `recording_info_dialog.py`, tests).

### Archivos afectados

- `app/core/recording/precog.py` — refactor de `snapshot()`
- `tests/test_precog.py` — test de verificación de la optimización

### Verificación ejecutada

- `python -m unittest tests.test_precog -v` → OK

## Paso 10 — Bugfix: loop_time_seconds mutation regression + favorite cap extraction

**Estado**: ✅ completado.

### Bug 1 — Mutación de `recording.loop_time_seconds` en `check_all_live_status`

**Problema**: `record_manager.py:check_all_live_status()` mutaba `recording.loop_time_seconds` al valor de `snap.adjusted_interval` (jitter incluido) después del snapshot:

```python
recording.loop_time_seconds = base_interval          # ← correcto: base config
snap = Precog.snapshot(recording, now=None)
recording.loop_time_seconds = snap.adjusted_interval  # ← BUG: muta a operacional
```

Esto rompía `Precog.stable_queue_key()` porque esa función lee `recording.loop_time_seconds` como el intervalo base/configurado para el badge de UI. El badge terminaba mostrando el key jittereado en vez del estable.

**Solución aplicada**:
- Se eliminó la mutación (`recording.loop_time_seconds = snap.adjusted_interval`).
- La métrica `check_dispatched` ahora usa `snap.adjusted_interval` directamente (el valor operacional para el scheduling).
- `recording.loop_time_seconds` queda estable en el valor base/configurado, preservando la semántica de `stable_queue_key()`.

### Bug 2 — Favorite cap duplicado

**Problema**: La regla `if is_favorite and adjusted_interval > 180: adjusted_interval = 180` estaba duplicada en `Precog.snapshot()` y `Precog.decide_queue()`.

**Solución aplicada**:
- Se extrajo a `Precog._apply_favorite_cap(adjusted_interval, recording) → int`.
- Ambos métodos (`snapshot`, `decide_queue`) ahora delegan en ese helper.
- `stable_queue_key()` NO aplica el cap (es deliberado: el badge muestra el intervalo base configurado, no el ajuste operacional por favorito).

### Archivos afectados

- `app/core/recording/precog.py` — `_apply_favorite_cap` extraído, `snapshot()` y `decide_queue()` lo usan
- `app/core/recording/record_manager.py` — se elimina mutación de `loop_time_seconds`, métrica usa `snap.adjusted_interval`
- `tests/test_precog.py` — tests para `_apply_favorite_cap` + regresión de `stable_queue_key`
- `tests/test_record_manager_precog.py` — assertion actualizada (base 300, no adjusted 60)
- `docs/PRECOG_PLAN_ES.md` — este documento actualizado

### Verificación ejecutada

- `python -m unittest tests.test_precog tests.test_record_manager_precog` → OK

## Paso 10 — Precog → UI notifications (event-driven snapshot propagation)

**Estado**: ✅ completado.

### Problema

La UI recomputaba `Precog.snapshot()` de forma independiente al ciclo operativo:
- `_update_badge_cache()` llamaba `Precog.snapshot()` para cada recording cada 1 segundo.
- `_fill_badges()` en `recording_card.py` llamaba `Precog.snapshot()` en cada `update_content()`.
- El ciclo operativo (`check_all_live_status`) ya computaba el mismo snapshot, pero los datos se descartaban después del dispatch.

Esto duplicaba trabajo: 2 snapshots por recording por ciclo (uno en operación, otro en UI).

### Solución aplicada

Se implementó un mecanismo **event-driven** de propagación de snapshots desde el ciclo operativo hacia la UI:

1. **`record_manager.py:check_all_live_status`** — captura los `PrecogSnapshot` en un dict keyeado por `rec_id`, los almacena como `recording._last_snapshot`, y publica un evento `"precog_snapshot_batch"` al finalizar el ciclo.

2. **`recordings_view.py`** — se suscribe a `"precog_snapshot_batch"`. El handler `_on_precog_snapshot_batch` actualiza `_badge_cache` con los datos del snapshot (queue key, likelihood, is_stale) sin llamar a `Precog.snapshot()`.

3. **`recording_card.py:_fill_badges`** — intenta leer `recording._last_snapshot` primero. Si no existe, cae en `Precog.snapshot()` como fallback (recording nuevo sin ciclo operativo previo).

4. **`_update_badge_cache`** — ya no computa Precog snapshots. Solo refresca las cards visibles y el repintado de lista. La cache de badges se nutre exclusivamente por eventos del ciclo operativo.

### Flujo de datos resultante

```
Ciclo operativo (~180s):
  check_all_live_status()
    → Precog.snapshot(rec) para cada recording monitoreado
    → recording._last_snapshot = snap
    → event_bus.publish("precog_snapshot_batch", {rec_id: snap, ...})

UI subscriber:
  _on_precog_snapshot_batch()
    → actualiza _badge_cache sin Precog.snapshot()
    → repinta list view si está en modo lista

Timer UI (1s):
  _on_refresh_tick()
    → _update_badge_cache() — solo actualiza cards visibles
    → refresh_all() — emite dataChanged, paint() lee de cache

Card badges:
  _fill_badges()
    → getattr(rec, "_last_snapshot", None) or Precog.snapshot(rec)
```

### Stale snapshot invalidation (must-fix regressions)

Durante una auditoría posterior se encontraron tres fugas de estado stale en el mecanismo de `_last_snapshot`:

1. **Rama `is_recording` en `check_all_live_status`** (`record_manager.py:430`):
   - Una grabación en curso (recording activo) saltaba todo el bloque de snapshot y solo actualizaba EMA. El `_last_snapshot` quedaba congelado desde el ciclo anterior, mostrando datos previos a que la grabación empezara.
   - **Fix**: `recording._last_snapshot = None` al entrar a la rama. La UI cae a `Precog.snapshot()` en tiempo real.

2. **Finally de `check_if_live`** (`record_manager.py:789`):
   - Después de ejecutar un chequeo (live→offline, offline→live, o cualquier transición), `_last_snapshot` seguía siendo el snapshot del ciclo operativo previo al chequeo, que ya no refleja el estado actual.
   - **Fix**: `recording._last_snapshot = None` en el finally block. Esto cubre todos los early returns (`is_recording`, `active_recorders`, `monitor_status=False`) y el flujo completo.

3. **`stop_monitor_recording`** (`record_manager.py:333`):
   - Al dejar de monitorear, el snapshot residual quedaba en el recording. Si se volvía a monitorear, la UI podía leer datos obsoletos hasta el próximo ciclo.
   - **Fix**: `recording._last_snapshot = None` después de limpiar los predictores.

### Semántica de frescura resultante

| Condición | `_last_snapshot` | UI lee de |
|---|---|---|
| Después de `check_all_live_status` (normal) | snapshot fresco | cache del batch |
| Grabación activa (`is_recording=True`) | `None` (invalidado) | `Precog.snapshot()` en tiempo real |
| Después de `check_if_live` | `None` (invalidado) | `Precog.snapshot()` hasta próximo ciclo |
| Monitoreo detenido | `None` (limpiado) | `Precog.snapshot()` si se consulta |
| Grabación sin ciclo previo | nunca se asignó | `Precog.snapshot()` (fallback natural) |

La regla es simple y conservadora: **cuando el estado del recording cambia de forma meaningful, se invalida el snapshot cacheado**. El fallback `getattr(rec, "_last_snapshot", None) or Precog.snapshot(rec)` en `recording_card.py:488` garantiza que siempre se tenga datos frescos, aunque con la penalidad de recomputar Precog cuando no hay cache.

### user_config NameError

En la rama `only_notify_no_record` de `check_if_live` (`record_manager.py:727`), se referenciaba `user_config.get("notify_loop_time")` pero `user_config` no era una variable definida en ese ámbito. El contexto correcto es `self.settings.user_config.get(...)`, idéntico al patrón usado en el resto del archivo.

**Fix**: `user_config.get(...)` → `self.settings.user_config.get(...)`.

### Thread safety

No hay problema de thread boundary porque qasync ejecuta el event loop de asyncio en el mismo thread que Qt. Los callbacks sync de `event_bus.publish()` se ejecutan en el mismo thread, por lo que las actualizaciones de UI son seguras.

### Archivos afectados

- `app/core/recording/record_manager.py` — captura snapshots y publica evento `precog_snapshot_batch`
- `app/qt/views/recordings_view.py` — suscripción al evento, handler `_on_precog_snapshot_batch`, `_update_badge_cache` simplificado
- `app/qt/components/recording_card.py` — `_fill_badges` lee `_last_snapshot` primero
- `tests/test_record_manager_precog.py` — test para `_last_snapshot` y evento publicado
- `tests/test_recordings_view_precog.py` — tests para `_on_precog_snapshot_batch`
- `tests/test_recording_card_badge.py` — tests para `_last_snapshot` en `_fill_badges`
- `docs/PRECOG_PLAN_ES.md` — este documento actualizado

### Verificación ejecutada

- `python -m unittest tests.test_precog` → OK
- `python -m unittest tests.test_record_manager_precog` → OK
- `python -m unittest tests.test_recording_card_badge` → OK
- `python -m unittest tests.test_recordings_view_precog` → OK
- `python -m unittest tests.test_precog tests.test_record_manager_precog tests.test_recording_card_badge tests.test_recordings_view_precog` → OK (todos)
- `python -m unittest discover` → 124 tests, OK

### Archivos afectados en el parche de regresiones

- `app/core/recording/record_manager.py` — 3 invalidaciones de `_last_snapshot` + fix `user_config` NameError
- `tests/test_record_manager_precog.py` — 3 tests nuevos: invalidation en `is_recording` branch, en `check_if_live` finally, y en `stop_monitor_recording`
- `docs/PRECOG_PLAN_ES.md` — documentadas las regresiones y la semántica de frescura resultante

## Qué sigue pendiente

1. **Baja prioridad: dar por cerrada formalmente la consolidación UI de Precog**
   - Todos los consumidores UI relevantes ya están migrados al método justo para su necesidad.

## Cierre formal de la consolidación UI de Precog

La consolidación de todos los consumidores UI sobre Precog está **formalmente cerrada** en esta fase. No quedan migraciones pendientes de lectores ni consumidores relevantes por mover.

### API pública recomendada

| Método | Para qué usarlo | Consumidores actuales |
|--------|----------------|----------------------|
| `Precog.snapshot(recording, now=None)` | Consumidores que necesitan el estado predictivo completo + decisión operativa + datos de UI en una sola foto coherente. **Punto de entrada preferido** para nuevos consumidores. | `record_manager.py`, `recording_card.py`, `recordings_view.py`, `live_forecast_dialog.py` |
| `Precog.forecast(recording, now=None)` | Consumidores livianos que solo necesitan forecast_details (ventana, confianza, score) sin adjusted_interval ni decisión de cola. | `recording_info_dialog.py` |
| `Precog.stable_queue_key(recording)` | Badge de cola en UI. Devuelve un key estable basado en el intervalo base configurado, sin jitter operacional. **No usar para decisiones de scheduling**. | `recordings_view.py` (badge cache) |
| `Precog.predict()` / `Precog.decide_queue()` | Compatibilidad y contratos derivados. **No** son el punto de entrada preferido para nuevos consumidores UI. | Tests, wrappers internos |

### Consumidores actuales — mapa completo

| Consumidor | Método Precog | Notas |
|---|---|---|
| `record_manager.py` | `snapshot()` | Punto de entrada operativo principal |
| `recording_card.py` | `snapshot()` / `_last_snapshot` | Lee snapshot cacheado del ciclo operativo |
| `recordings_view.py` | `snapshot()` + `stable_queue_key()` | Snapshot para datos, stable_queue_key para badge |
| `live_forecast_dialog.py` | `snapshot()` | Diálogo pesado de predicciones |
| `recording_info_dialog.py` | `forecast()` | Diálogo liviano bajo demanda |

### ¿Qué sigue?

No hay más consumidores UI relevantes que migrar. El próximo trabajo de valor está en la **simplificación y documentación de la API de Precog**, no en seguir moviendo lectores.

## Punto de reentrada para futuras sesiones

La notificación Precog → UI ya está implementada (Paso 10), la deuda de consistencia temporal ya quedó cerrada, `live_forecast_dialog.py` ya fue consolidado sobre `Precog.snapshot()` y `recording_info_dialog.py` ya usa `Precog.forecast()` como camino liviano. La consolidación UI de Precog puede darse por cerrada. El siguiente paso recomendado es:

1. dar por cerrado formalmente el tramo de consolidación de consumidores UI de Precog,
2. el próximo valor ya está más en simplificar/documentar la API que en seguir migrando lectores.

## Referencias

- `docs/INTELLIGENCE_ES.md`
- `app/core/recording/history_manager.py`
- `app/core/recording/record_manager.py`
- `app/models/recording/recording_model.py`
- `app/core/recording/predictor_metrics.py`
- `app/core/recording/precog.py`
- `tests/test_precog.py`
