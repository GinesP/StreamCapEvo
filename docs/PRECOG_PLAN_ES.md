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

- `app/core/recording/precog.py`

### Clase pública prevista

- `Precog`

### Responsabilidades públicas previstas

#### 1. `predict(recording, now=None)`

Debe devolver un snapshot unificado con datos como:

- `likelihood`
- `confidence`
- `priority_score`
- `consistency_score`
- `adjusted_interval`
- `forecast_details`

#### 2. `decide_queue(recording, now=None)`

Debe encapsular la decisión operativa mínima actual:

- `should_check`
- `queue_priority` (`F`, `M`, `S`)
- `adjusted_interval`
- `likelihood`
- `reason`

#### 3. `get_ui_state(recording, now=None)`

Debe ofrecer a la UI una vista consistente para evitar llamadas dispersas o lógica duplicada.

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

## Paso 2 — Migrar consumidores de lectura de bajo riesgo

Mover primero los consumidores que solo leen datos predictivos:

- `app/qt/components/recording_card.py`
- `app/qt/components/recording_info_dialog.py`
- `app/qt/views/recordings_view.py`

Objetivo:

- reducir acceso directo a `HistoryManager`,
- comprobar que Precog sirve como punto de entrada estable.

## Paso 3 — Migrar `live_forecast_dialog.py`

Revisar y migrar:

- `app/qt/components/live_forecast_dialog.py`

Este paso merece atención especial porque aquí puede haber lógica derivada o duplicada.

## Paso 4 — Mover la decisión de cola a Precog

Integrar Precog en:

- `app/core/recording/record_manager.py`

Objetivo:

- que la decisión `likelihood -> adjusted_interval -> queue` quede centralizada.

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
- [ ] Crear `app/core/recording/precog.py`
- [ ] Migrar consumidores de lectura a Precog
- [ ] Migrar decisión operativa de cola a Precog
- [ ] Evaluar limpieza posterior una vez centralizado

## Punto de reentrada para futuras sesiones

Si retomamos este trabajo en otra sesión, el siguiente paso recomendado es:

1. crear `app/core/recording/precog.py`,
2. implementar `Precog.predict()` con comportamiento equivalente al actual,
3. migrar primero un consumidor de bajo riesgo.

## Referencias

- `docs/INTELLIGENCE_ES.md`
- `app/core/recording/history_manager.py`
- `app/core/recording/record_manager.py`
- `app/models/recording/recording_model.py`
- `app/core/recording/predictor_metrics.py`
