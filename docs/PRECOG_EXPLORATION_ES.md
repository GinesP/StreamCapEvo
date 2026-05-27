# Exploración Arquitectónica: Sistema de Inteligencia/Predicción

## Resumen Ejecutivo

1. **`HistoryManager` ya es una fachada estática** — todos sus métodos son `@staticmethod`. No hay instancias, no hay estado mutable dentro de `HistoryManager`. Pero consume datos desde `Recording`, que SÍ tiene estado y es una mezcla de modelo de persistencia y modelo de predicción (violación de Single Responsibility).

2. **La lógica de predicción está repartida en 4 capas**: `Recording.increment_live_counts()` (modelo), `HistoryManager` (cálculo), `_get_forecast_time_info()` en UI (duplicación), y `RecordingManager.check_all_live_status()` (orquestación). No hay un único punto de entrada para "dado un stream, ¿qué decisión tomamos?".

3. **`historical_intervals` y `live_sessions` SÍ se superponen pero no son fuentes de verdad opuestas**: `historical_intervals` (FIFO-5, resolución de hora) detecta **cambios de horario**; `live_sessions` (120 max, resolución de minuto) provee **precisión de ventana**. La confusión real está en que `_get_forecast_time_info()` en el diálogo solo usa intervals, mientras `get_forecast_details()` usa ambos con reglas de precedencia implícitas.

4. **Hay precedencia implícita documentada**: en `history_manager.py` líneas 225-231, si `session_stats` tiene ventana, **siempre** reemplaza a la ventana de intervals. El score usa lógica de "el que gane" — si `session_component > score`, gana sesiones. Esto es correcto pero invisible para quien no lea el código.

5. **Duplicación confirmada**: `_get_forecast_time_info()` en `live_forecast_dialog.py` (líneas 32-81) replica el clustering de `_cluster_hours` y el cálculo de `display_hour` que ya existe en `get_forecast_details()`. La UI tiene SU PROPIA máquina de estados (live_range/expected/delayed/countdown) que debería ser parte del núcleo, no de la UI.

6. **5 consumidores distintos llaman a HistoryManager desde 3 capas diferentes**: `RecordingManager` (core), `LiveForecastDialog` (UI), `QtRecordingCard` (UI), `RecordingInfoDialog` (UI), `QtRecordingsView` (UI). Cada uno recalcula `get_likelihood_score()` por separado — no hay caché ni coherencia de ciclo.

7. **`PredictorMetricsStore` es puramente observabilidad**: escribe a `predictor_metrics.db` (SQLite con WAL). Solo lo consume `scripts/predictor_metrics_report.py`. No hay retroalimentación al sistema desde las métricas — es unidireccional y de bajo coste operativo.

8. **No existe un concepto de "consulta de decisión unificada"**: para saber qué cola, qué intervalo, qué prioridad, qué likelihood, qué ventana, qué consistencia tiene un streamer, hay que llamar a 3-4 métodos distintos repartidos entre `HistoryManager` y atributos directos de `Recording`.

9. **La UI llama a HistoryManager en el hilo principal** (`_populate_list` en live_forecast_dialog.py, `_fill_badges` en recording_card.py), lo que significa que recálculos de forecast (que iteran sesiones con pesos exponenciales) compiten con el renderizado.

10. **`Recording` es a la vez fuente de persistencia y de inteligencia**: almacena `historical_intervals`, `live_sessions`, `priority_score`, `consistency_score`, y también `last_seen_live`. Los métodos `increment_live_counts()`, `start_live_session()`, `end_live_session()` mutan estos campos. Separar la inteligencia del modelo de dominio simplificaría tests y evolutividad.

---

## Mapa de Módulos/Archivos y Responsabilidades

| Archivo | Rol | Responsabilidades de inteligencia |
|---------|-----|-----------------------------------|
| `app/models/recording/recording_model.py` | Modelo de dominio + inteligencia embebida | `increment_live_counts()` — actualiza `historical_intervals`, `priority_score` (EMA), `consistency_score`, recency decay. `start_live_session()` / `end_live_session()` — maneja `live_sessions`. `split_stale_live_session_if_needed()`. |
| `app/core/recording/history_manager.py` | Cálculo de predicción | `get_likelihood_score()` — score combinado. `get_forecast_details()` — score, confidence, window, next_slot, horizons, reason_key. `get_adjusted_interval()` — traduce score a intervalo con jitter. `_session_stats()` — análisis de sesiones reales. `_cluster_hours()` — agrupación de horas. `_parse_scheduled_windows()` — ventanas programadas. |
| `app/core/recording/record_manager.py` | Orquestación + colas | `check_all_live_status()` — ciclo principal que llama a `get_likelihood_score()` y `get_adjusted_interval()`, decide cola (F/M/S), despacha. `check_if_live()` — ejecuta detección, llama a `increment_live_counts()`. `_record_predictor_metric()` — instrumentación. |
| `app/qt/components/live_forecast_dialog.py` | UI: diálogo de pronóstico | `_populate_list()` — llama a `get_likelihood_score()` y `get_forecast_details()`. `_get_forecast_time_info()` — duplica lógica de clustering + display_hour. `ForecastItemWidget` — consume forecast details. |
| `app/qt/components/recording_card.py` | UI: tarjeta de streamer | `_fill_badges()` — llama a `get_likelihood_score()` para badge. |
| `app/qt/components/recording_info_dialog.py` | UI: diálogo de info | `get_forecast_details()` para mostrar next_window. |
| `app/qt/views/recordings_view.py` | UI: vista de listado | `_likelihood()` — llama a `get_likelihood_score()` para sorting/filtro. |
| `app/core/recording/predictor_metrics.py` | Instrumentación/observabilidad | `PredictorMetricsStore` — escribe a SQLite. `summarize()` — produce `MetricsSummary` con percentiles. Solo lo usa el script de reporte. |

### Grafo de llamadas (simplificado)

```
RecordingManager.check_all_live_status()
  ├── Recording.increment_live_counts()          [si ya está grabando]
  ├── HistoryManager.get_likelihood_score()       → get_forecast_details()
  │     ├── _session_stats()                      [live_sessions → score + window]
  │     ├── _parse_scheduled_windows()
  │     ├── _cluster_hours()
  │     └── Recording.consistency_score, priority_score
  ├── HistoryManager.get_adjusted_interval()
  └── -> dispatch a cola F/M/S

RecordingManager.check_if_live()
  ├── Recording.increment_live_counts()           [actualiza todo]
  ├── Recording.start_live_session() / end_live_session() / split_stale()
  └── PredictorMetricsStore.record_event()        [check_result]

LiveForecastDialog._populate_list()
  ├── _get_forecast_time_info()                   [DUPLICA cluster + display_hour]
  └── HistoryManager.get_likelihood_score() + get_forecast_details()
```

---

## Fuentes de Verdad — Precedencia Real Detectada

### Datos crudos (persistencia)

| Fuente | Dónde se almacena | Granularidad | Límite |
|--------|--------------------|--------------|--------|
| `historical_intervals` | `Recording.historical_intervals` (dict día→horas) | Hora | 5 slots FIFO por día |
| `live_sessions` | `Recording.live_sessions` (list[dict]) | Minuto | 120 sesiones, últ. 90 días |
| `priority_score` | `Recording.priority_score` (float) | EMA continuo | N/A |
| `consistency_score` | `Recording.consistency_score` (float) | Derivado de intervals | 0.0–1.0 |
| `scheduled_recording` | `Recording.scheduled_recording` + `scheduled_start_time` + `monitor_hours` | Config fija | N/A |

### Precedencia en score (get_forecast_details, history_manager.py:155-291)

1. **Baseline**: `0.15`
2. **Historical Intervals**: `max(0.25 + proximity * 0.55)` — domina si hay horas activas cerca
3. **Session Stats**: si `session_component > score`, gana sesiones (línea 221-222)
4. **Ventana de UI**: sessions SIEMPRE reemplaza a intervals si tiene datos de minuto (líneas 228-230)
5. **Consistency score**: contribuye hasta `+0.12`
6. **Priority score**: contribuye hasta `+0.12`
7. **Scheduled windows**: si está dentro → `score = 0.95`, gana absolute
8. **Penalizaciones**: inactividad >14d (`×0.82`), >45d (`×0.70`)
9. **Capping**: `max(0.05, min(1.0, score))`

**Regla de resolución clave**: Si hay datos de sesión (`live_sessions`), la ventana y el próximo slot se toman de sesiones (minuto-grano), NO de intervals. El score usa el máximo entre ambos componentes.

### Precedencia en intervalo (get_adjusted_interval, history_manager.py:302-339)

1. `likelihood >= 0.9` → **60s** (Fast)
2. `likelihood >= 0.5` → **base//2** (Medium)
3. `priority < 0.01 AND check_count > 30` → **base*3** (Deep Sleep)
4. `likelihood <= 0.15` → **base*1.5** (Slow)
5. Default → **base** (Normal)
6. Favoritos: **nunca > 180s**
7. Jitter: 15% aleatorio sobre el target

### Precedencia en cola (check_all_live_status, record_manager.py:450-494)

- `loop_time_seconds <= 60` → Fast
- `loop_time_seconds <= 180` → Medium
- El resto → Slow

---

## Acoplamientos y Duplicaciones

### Duplicación #1 (CRÍTICA): `_get_forecast_time_info()` replica clustering
- **Archivo**: `live_forecast_dialog.py:32-81`
- **Qué replica**: `_cluster_hours()`, cálculo de `display_hour`, `window_text` — exactamente la misma lógica que en `get_forecast_details()` (history_manager.py:183-206)
- **Impacto**: Si se cambia la lógica de clustering (ej. max_gap de 4h a 3h), hay que cambiar en DOS sitios. Ya pasó con el fix de next_slot_text del 2026-05-10 — se arregló en `get_forecast_details` pero no en `_get_forecast_time_info`.
- **Evidencia**: El comentario en línea 36 dice textual: "Uses the SAME cluster logic as HistoryManager.get_forecast_details" — reconocen la duplicación.

### Duplicación #2: Consistencia de cluster se recalcula 5 veces por streamer
- Cada UI component llama a `get_likelihood_score()` independientemente.
- Para 100 streamers, `get_forecast_details` se ejecuta 500+ veces en un ciclo de UI (5 componentes × 100 streamers).
- No hay caché, no hay coherencia entre el valor que usó `check_all_live_status` y el que muestra la UI.

### Acoplamiento #1: Recording es modelo de persistencia Y de inteligencia
- `increment_live_counts()` no debería estar en el modelo. Mezcla EMA (estadística) con persistencia.
- Si se cambia la fórmula de EMA, se modifica `Recording` — viola Single Responsibility.
- `historical_intervals` y `live_sessions` se serializan/deserializan junto con datos de configuración.

### Acoplamiento #2: HistoryManager conoce la estructura interna de Recording
- Accede directamente a `recording.historical_intervals`, `recording.live_sessions`, `recording.consistency_score`, `recording.priority_score`, `recording.last_seen_live`, `recording.scheduled_recording`.
- Si se renombra un campo en Recording, se rompe HistoryManager.

### Acoplamiento #3: La UI llama al core en el hilo principal
- `live_forecast_dialog._populate_list()` llama a `get_forecast_details()` sincrónicamente — bloquea el event loop de Qt si hay muchos streamers.
- `recording_card._fill_badges()` llama a `get_likelihood_score()` en el constructor de cada tarjeta.

### Duplicación #3: Determinación de cola (F/M/S) en 3 sitios
1. `record_manager.py:452-457` — lógica de dispatch
2. `recordings_view.py:284-290` — badge de cola en vista de lista
3. `recording_card.py:464-468` — badge de cola en tarjeta
- Los 3 replican `<=60 → F, <=180 → M, >180 → S`.
- Si se cambian los thresholds, hay que cambiar en 3 sitios.

---

## Propuesta de Arquitectura: PrecogCore

### Interfaces sugeridas

```python
class PrecogCore:
    """
    Núcleo único de inteligencia predictiva.
    
    - Toma decisiones para un Recording en un momento dado.
    - Es STATELESS (toda la data viene del Recording o de un snapshot).
    - Reemplaza a HistoryManager y absorbe lógica duplicada de UI.
    """

    @dataclass
    class Prediction:
        score: float                    # likelihood 0.0-1.0
        confidence: str                 # "high" | "medium" | "low"
        reason_key: str                 # clave de i18n
        next_slot_text: str             # "20:00"
        window_text: str                # "20:00-23:00"
        avg_delay_minutes: int | None
        horizons: dict[int, float]      # {15: 0.8, 30: 0.6, ...}

    @dataclass
    class QueueDecision:
        queue: str                      # "F" | "M" | "S"
        interval_seconds: int           # con jitter aplicado
        is_fast: bool
        is_medium: bool
        is_slow: bool

    @dataclass
    class StreamerState:
        """Estado de UI: cuándo se espera al streamer."""
        state: str                      # "live_range" | "expected" | "delayed" | "countdown" | "upcoming" | "none"
        text: str
        prefix: str
        color: str
        # ... todo lo que hoy está en _get_forecast_time_info

    @staticmethod
    def predict(recording: Recording, now: datetime | None = None) -> Prediction:
        """Score + ventana + razones. Reemplaza get_forecast_details()."""

    @staticmethod
    def decide_queue(recording: Recording, base_interval: int) -> QueueDecision:
        """Cola + intervalo. Reemplaza get_adjusted_interval() + lógica de thresholds."""

    @staticmethod
    def time_state(recording: Recording, now: datetime | None = None) -> StreamerState:
        """Estado de UI. Reemplaza _get_forecast_time_info()."""
    
    @staticmethod
    def forecast_for(recording: Recording, dt: datetime) -> 'Prediction':
        """Score para un datetime arbitrario. Usado por horizons."""

class PrecogData:
    """
    Responsable de MUTAR los datos de inteligencia en Recording.
    
    - Único punto que modifica historical_intervals, live_sessions, 
      priority_score, consistency_score, last_seen_live.
    - Reemplaza increment_live_counts(), start_live_session(), etc.
    - Permite testear mutaciones sin tocar Recording.
    """

    @staticmethod
    def record_live_check(recording: Recording, is_live: bool, now: datetime, config: dict) -> None:
        """Actualiza intervals, EMA, consistency, sesiones."""

    @staticmethod
    def start_session(recording: Recording, detected_at: datetime) -> None:
    @staticmethod
    def end_session(recording: Recording, ended_at: datetime) -> None:
    @staticmethod
    def split_stale_session(recording: Recording, now: datetime) -> bool:
```

### Responsabilidades por componente

| Componente | Responsabilidad | Reemplaza |
|------------|----------------|-----------|
| `PrecogCore.predict()` | Score combinado + ventana + confidence + reason + horizons | `HistoryManager.get_forecast_details()` + `get_likelihood_score()` |
| `PrecogCore.decide_queue()` | Cola (F/M/S) + intervalo con jitter + regla de favoritos | `HistoryManager.get_adjusted_interval()` + lógica duplicada de thresholds F/M/S |
| `PrecogCore.time_state()` | Estado de UI para el diálogo (live_range/expected/delayed/countdown) | `_get_forecast_time_info()` en live_forecast_dialog.py |
| `PrecogData.record_live_check()` | Mutación de intervals, EMA, consistency, recency decay | `Recording.increment_live_counts()` |
| `PrecogData.start_session()` / `end_session()` / `split_stale_session()` | Gestión de sesiones de live | `Recording.start_live_session()` / `end_live_session()` / `split_stale_live_session_if_needed()` |
| `RecordingManager` (reducido) | Solo orquestación: llamar a PrecogCore, despachar a colas | Estado actual |
| UI components | Llamar a `PrecogCore.predict()` y `PrecogCore.time_state()` — NUNCA HistoryManager | Estado actual |

### Mapa de migración

```
HOY:
Recording.increment_live_counts()   → muta datos en Recording
  └── historical_intervals, priority_score, consistency_score

HistoryManager.get_forecast_details() → lee Recording, computa score+window
  └── llama a _session_stats(), _cluster_hours(), _parse_scheduled_windows()

RecordManager.check_all_live_status() → orquesta, llama a HistoryManager

_get_forecast_time_info() (UI)       → DUPLICA cluster+display_hour

DESPUÉS:
Recording.increment_live_counts()   → DELEGA a PrecogData.record_live_check()
HistoryManager.*                    → DELEGA a PrecogCore.* (o se elimina)
RecordManager.check_all_live_status → llama a PrecogCore.decide_queue()
_get_forecast_time_info()           → llama a PrecogCore.time_state()
UI cards/dialogs                    → llaman a PrecogCore.predict()
```

---

## `predictor_metrics.db` / JSONL — Nota

| Aspecto | Detalle |
|---------|---------|
| **Dónde se produce** | `record_manager.py` — 3 call sites: `check_dispatched` (línea 474), `check_result:is_live` (línea 742), `check_result:not_live` (línea 781) |
| **Quién lo consume** | Solo `scripts/predictor_metrics_report.py` — un script CLI invocado a demanda. **Ningún componente del sistema en producción lo consume.** |
| **Formato actual** | SQLite (`predictor_metrics.db`) con migración desde legacy JSONL. WAL + synchronous=NORMAL. |
| **Volumen típico** | 2 eventos por ciclo por streamer monitorizado. Para 100 streamers con ciclo de 180s → ~40,000 eventos/día. |
| **Utilidad real** | **ALTA** — el reporte con percentiles (p50/p95/p99) detectó congestión de cola (p95=570s de dispatch_wait) que el promedio escondía. La breakdown F/M/S permitió decisiones de ajuste de workers. |
| **Sobrecoste** | **MÍNIMO** — escribe en un hilo separado con protección de lock. La escritura SQLite es barata (WAL + batch). El único coste real es que el `summarize()` recorre todos los registros en memoria. |
| **Recomendación** | **Conservarlo**. Pero considerar añadir un consumidor interno (ej. alerta si dispatch_wait_p95 > 300s) en vez de solo un script externo. No eliminarlo. |

---

## Riesgos de Migración y Estrategia Incremental

### Riesgos

1. **R1 — Regression en precisión de predicción**: Cualquier refactor de `get_forecast_details()` puede alterar scores existentes. Los tests existentes deben cubrir los casos borde.
2. **R2 — Acoplamiento UI-core**: Mover `_get_forecast_time_info` al core puede introducir dependencias de i18n (`tr()`) o de UI en el core. **Solución**: `StreamerState` solo devuelve claves de estado + datos, no texto traducido.
3. **R3 — HistoryManager ya tiene 3 consumidores UI que dependen de su API actual**: No se puede eliminar sin coordinar cambios en UI.
4. **R4 — Recording sigue siendo el modelo persistido**: Si `PrecogData` muta datos, debe mantener compatibilidad con `to_dict()`/`from_dict()`.

### Estrategia en 6 pasos

#### Paso 1: Extraer PrecogCore como fachada (SIN migrar llamadores)
- Crear `app/core/intelligence/precog_core.py`
- Implementar `PrecogCore.predict()` como wrapper que llama a `HistoryManager.get_forecast_details()`
- Implementar `PrecogCore.decide_queue()` como wrapper que llama a `get_adjusted_interval()`
- Implementar `PrecogCore.time_state()` absorbiendo la lógica de `_get_forecast_time_info()`
- **No cambiar ningún llamador todavía**
- **Riesgo**: mínimo — es solo un wrapper
- **Test**: `PrecogCore.predict(x) == HistoryManager.get_forecast_details(x)` para N streamers

#### Paso 2: Migrar UI a PrecogCore
- `live_forecast_dialog.py`: reemplazar `_get_forecast_time_info()` con `PrecogCore.time_state()`
- `recording_card.py`: reemplazar `get_likelihood_score()` con `PrecogCore.predict().score`
- `recording_info_dialog.py`: reemplazar `get_forecast_details()` con `PrecogCore.predict()`
- `recordings_view.py`: reemplazar `_likelihood()` con `PrecogCore.predict().score`
- **Riesgo**: medio — hay que verificar que `time_state()` devuelva exactamente los mismos códigos de estado que la función duplicada

#### Paso 3: Migrar RecordingManager a PrecogCore
- `check_all_live_status()`: usar `PrecogCore.predict()` y `PrecogCore.decide_queue()`
- Eliminar el import directo de `HistoryManager` en `record_manager.py`
- **Riesgo**: medio — `decide_queue()` debe replicar exactamente la lógica de jitter + favoritos

#### Paso 4: Extraer PrecogData de Recording
- Mover `increment_live_counts()`, `start_live_session()`, `end_live_session()`, `split_stale_live_session_if_needed()` a `PrecogData`
- Recording conserva los campos pero delega las mutaciones
- **Riesgo**: alto — `increment_live_counts()` es llamado desde `check_all_live_status()` Y `check_if_live()`. Cualquier error aquí afecta a la recolección de datos históricos.

#### Paso 5: Deprecar HistoryManager y limpiar duplicaciones
- Marcar `HistoryManager` como `@deprecated`
- Eliminar `_get_forecast_time_info()` del dialog (ya reemplazado en Paso 2)
- Unificar la determinación de cola F/M/S (hoy en 3 sitios) en una sola función de `PrecogCore`
- **Riesgo**: bajo si Pasos 1-3 fueron correctos

#### Paso 6: Añadir caché de ciclo (opcional, si hay problemas de rendimiento)
- Durante `check_all_live_status()`, almacenar `PrecogCore.Prediction` en un dict temporal `{rec_id: prediction}`
- Los componentes UI pueden leer de ese caché en vez de recalcular
- **Riesgo**: bajo — es aditivo

### Resumen de pasos

| Paso | Qué | Riesgo | Dependencias |
|------|-----|--------|-------------|
| 1 | Crear PrecogCore wrapper | Bajo | Ninguna |
| 2 | Migrar UI a PrecogCore | Medio | Paso 1 |
| 3 | Migrar RecordingManager a PrecogCore | Medio | Paso 1 |
| 4 | Extraer PrecogData | Alto | Pasos 2-3 |
| 5 | Deprecar HistoryManager | Bajo | Pasos 1-4 |
| 6 | Caché de ciclo | Bajo | Paso 3 |

---

## Ready for Proposal

**Sí**. Esta exploración ha identificado:

- Las 6 fuentes de datos y su precedencia real
- Las 2 duplicaciones confirmadas (cluster logic en UI, thresholds de cola)
- Los 5 consumidores y su grafo de dependencias
- La arquitectura PrecogCore con interfaces concretas
- Una estrategia incremental en 6 pasos

El siguiente paso es escribir una **SDD Proposal** formal con `sdd-propose`, que defina alcance, impacto y plan de implementación. El usuario debe saber que:

1. El Paso 1 (wrapper) se puede hacer en horas sin riesgo de regresión.
2. El Paso 4 (PrecogData) es el más riesgoso y merece diseño detallado antes de codificar.
3. La duplicación de `_get_forecast_time_info` es la deuda técnica más urgente porque puede divergir.
