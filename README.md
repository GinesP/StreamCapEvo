<div align="center">
  <img src="./assets/images/logo.svg" alt="StreamCapEvo" />
</div>
<p align="center">
  <img alt="Python version" src="https://img.shields.io/badge/python-3.10%2B-blue.svg">
  <a href="https://github.com/GinesP/StreamCapEvo">
      <img alt="Supported Platforms" src="https://img.shields.io/badge/Platforms-Win%20%7C%20Mac%20%7C%20Linux-6B5BFF.svg"></a>
  <a href="https://hub.docker.com/r/GinesP/StreamCapEvo/tags">
      <img alt="Docker Pulls" src="https://img.shields.io/docker/pulls/GinesP/StreamCapEvo?label=Docker%20Pulls&color=2496ED&logo=docker"></a>
  <a href="https://github.com/GinesP/StreamCapEvo/releases/latest">
      <img alt="Latest Release" src="https://img.shields.io/github/v/release/GinesP/StreamCapEvo"></a>
  <a href="https://github.com/GinesP/StreamCapEvo/releases/latest">
      <img alt="Downloads" src="https://img.shields.io/github/downloads/GinesP/StreamCapEvo/total"></a>
</p>
<div align="center">
  Español / <a href="./README_EN.md">English</a>
</div><br>

# StreamCapEvo

StreamCap es un cliente multiplataforma para grabar directos, basado en FFmpeg y StreamGet. Permite monitorizar, grabar y gestionar streams de más de 40 plataformas con soporte para grabación por lotes, comprobación periódica, horarios de monitorización y transcodificación automática.

## Características

- **Multiplataforma**: Windows, macOS, Linux y modo web.
- **Monitorización continua**: detecta cuándo un canal empieza a emitir y arranca la grabación.
- **Horarios de comprobación**: limita la monitorización a franjas horarias configurables.
- **Formatos de salida**: TS, FLV, MKV, MOV, MP4, MP3, M4A y otros formatos soportados por FFmpeg.
- **Transcodificación automática**: puede convertir las grabaciones a MP4 al finalizar.
- **Notificaciones**: avisos de inicio y fin de directo mediante los canales configurados.
- **Priorización inteligente**: ajusta frecuencia de comprobación y orden de streams según actividad histórica.
- **Interfaz Qt**: aplicación de escritorio moderna con temas claro/oscuro y selección de acento.

## Funciones inteligentes

- **Predicción de horarios activos**: aumenta la frecuencia de comprobación en los tramos donde un canal suele estar activo.
- **Decaimiento de prioridad**: reduce gradualmente la prioridad de canales inactivos durante largos periodos.
- **Etiquetas de probabilidad**: ayuda a identificar streams con mayor probabilidad de iniciar directo pronto.
- **Ordenación automática**: mantiene arriba los streams activos y prioriza el resto por puntuación.
- **Documentación técnica**: consulta `docs/INTELLIGENCE_ES.md` para más detalle sobre el sistema de inteligencia.

## Inicio rápido desde código fuente

Requisitos mínimos:

- Python 3.10 o superior.
- FFmpeg instalado y disponible en el `PATH`.
- Dependencias Python instaladas desde `requirements.txt`.

```bash
git clone https://github.com/GinesP/StreamCapEvo.git
cd StreamCap
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python main_qt.py
```

En Linux/macOS, activa el entorno con:

```bash
source .venv/bin/activate
```

Si FFmpeg no está disponible, descárgalo desde la página oficial: <https://ffmpeg.org/download.html>.

## Ejecución con Docker

```bash
docker compose up -d
```

Para detener los contenedores:

```bash
docker compose down
```

## Plataformas soportadas

StreamCap soporta plataformas nacionales e internacionales, entre ellas:

- Douyin, TikTok, Kuaishou, Huya, Douyu, Bilibili, Rednote, YY, Acfun, Blued, JD Live y Taobao Live.
- Twitch, PandaTV, SOOP, TwitCasting, CHZZK, Shopee, YouTube, LiveMe, FlexTV, PopkonTV, Bigo Live y otras.

Normalmente se utiliza la URL de la sala o del perfil del canal. Ejemplos:

```text
Douyin:
https://live.douyin.com/745964462470
https://v.douyin.com/iQFeBnt/

TikTok:
https://www.tiktok.com/@pearlgaga88/live

Twitch:
https://www.twitch.tv/monster7

YouTube:
https://www.youtube.com/watch?v=5KpV0y_hNXQ
```

## Configuración y versión

- La versión técnica vive en `pyproject.toml`.
- `config/version.json` contiene la información visible en la aplicación.
- Usa `scripts/bump_version.py --check` para validar que ambos archivos están sincronizados.

## Documentación

- Documentación técnica de inteligencia: `docs/INTELLIGENCE_ES.md`.
- Distribución Windows: `docs/WINDOWS_DISTRIBUTION.md`.
- README en inglés: `README_EN.md`.
- Wiki del proyecto: <https://github.com/GinesP/StreamCapEvo/wiki>.

## Licencia

StreamCap se publica bajo Apache License 2.0. Consulta `LICENSE` para más información.

## Agradecimientos

Este proyecto se apoya en StreamGet, FFmpeg y el ecosistema Qt/PySide para proporcionar grabación y gestión de streams de forma estable y extensible.
