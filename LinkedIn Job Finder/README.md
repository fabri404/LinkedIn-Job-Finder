# LinkedIn Job Finder

**Herramienta de automatización construida con IA** para acelerar la búsqueda de empleo en LinkedIn.

Desarrollada en colaboración con Claude (Anthropic), esta herramienta escanea tu feed de LinkedIn en busca de publicaciones laborales relevantes, las analiza con un sistema inteligente de doble filtrado y te deja abiertas solo las búsquedas laborales reales para que las revises. Pensada para desarrolladores junior que necesitan optimizar su tiempo de búsqueda.

## ¿Qué hace?

En lugar de scrollear manualmente durante horas buscando oportunidades entre cientos de posts, LinkedIn Job Finder automatiza ese proceso:

1. Inicia sesión en tu cuenta de LinkedIn y refresca el feed.
2. Scrollea el feed durante el tiempo que vos elijas.
3. Analiza cada publicación buscando coincidencias con tus palabras clave.
4. Abre en pestañas nuevas cada post que matchea.
5. Ejecuta un **segundo filtro inteligente**: lee el contenido completo de cada pestaña y analiza patrones para determinar si es una búsqueda laboral real o un post informativo/motivacional. Si no es una oferta real, cierra la pestaña automáticamente.
6. Te deja solo las publicaciones verificadas como búsquedas reales.

## Sistema de doble filtrado

### Filtro 1 — Keywords

Analiza el texto de cada post en el feed. Si contiene al menos una de tus palabras clave configuradas en `keywords.txt`, lo marca como candidato y abre la publicación en una pestaña nueva. Este filtro es intencionalmente amplio para no perder oportunidades.

### Filtro 2 — Análisis inteligente de patrones

Recorre cada pestaña abierta y analiza su contenido con un sistema de puntuación que distingue ofertas laborales reales de posts informativos. Cada post recibe un score basado en indicadores positivos y negativos.

**Indicadores positivos** (señales de oferta real):

- Frases de contratación: "estamos buscando", "sumate a", "we are hiring"
- Sección de requisitos: "requisitos excluyentes", "perfil ideal", "must have"
- Pedido de postulación: "enviá tu CV a", "escríbeme por DM", "apply now"
- Email de contacto real (no genéricos de plataformas)
- Lista de posiciones abiertas con múltiples puestos
- Modalidad de trabajo: "híbrida", "remoto", "lunes a viernes"
- Descripción de tareas y responsabilidades
- Mención de beneficios o sueldo

**Indicadores negativos** (señales de post informativo):

- Lista de plataformas de empleo (Upwork, Workana, Remotive, etc.)
- Exceso de links externos informativos
- Frases de engagement: "seguime", "compartilo", "guardá este post"
- Preguntas retóricas: "¿cansado de la oficina?", "¿dónde conseguir trabajo?"
- Exceso de emojis decorativos de lista

Un post necesita **score ≥ 3** para ser considerado búsqueda real. En consola se muestra el detalle de cada análisis con el score y las razones que sumaron o restaron puntos.

**Ejemplo de clasificación:**

| Post | Score | Resultado |
|---|---|---|
| "¿Cansado de la oficina? Plataformas para trabajo remoto: Upwork, Workana..." | -21 | Falso positivo |
| "En TEKNOS estamos buscando un Trainee DevOps. Requisitos: ... Enviá tu CV a rrhh@teknosgroup.com" | +17 | Búsqueda real |
| "¡Seguimos creciendo! Posiciones abiertas: QA JR, Dev PL/SQL, Líder Full Stack..." | +10 | Búsqueda real |

## Stack técnico

- **Python 3.10+**
- **Selenium WebDriver** para automatización del navegador
- **JavaScript injection** para extracción robusta del DOM de LinkedIn
- **Sistema de scoring por patrones** para clasificación inteligente de contenido

## Requisitos previos

- Python 3.10 o superior
- Google Chrome instalado
- ChromeDriver compatible con tu versión de Chrome
- Una cuenta de LinkedIn

## Instalación

```bash
cd linkedin_job_finder

pip install -r requirements.txt

cp .env.example .env
```

Editá el archivo `.env` con tus credenciales de LinkedIn.

## Uso

### Dashboard (sin terminal)

Abrí **LinkedIn Job Finder** desde el menú de aplicaciones, o corré:

```bash
python3 dashboard.py --open   # http://localhost:8765
```

| Botón | Qué hace |
|---|---|
| Iniciar loop | Corre 24/7 sin ventana (feed, grupos, búsquedas de publicaciones y Empleos) |
| Correr una vuelta | Una sola vuelta y termina |
| Con ventana (login) | Abre Chrome visible para iniciar sesión o resolver una verificación de LinkedIn |
| Detener | Cierra Chrome y guarda el estado |

Pestañas: borradores creados, empleos sin email (Easy Apply guardado o postulación manual),
vacantes para contactar por LinkedIn, búsquedas de publicaciones (agregar/quitar; se aplican
al reiniciar el loop) y actividad reciente. Solo escucha en `127.0.0.1` y nunca envía mails:
los borradores quedan en Gmail.

### Terminal

```bash
python3 main.py            # loop continuo
python3 main.py --once     # una vuelta
python3 main.py --dry-run  # arma los mails sin crear borradores
```

## Personalización

### Palabras clave — `keywords.txt`

Una keyword por línea. El primer filtro captura todo post que contenga al menos una de estas palabras; el segundo filtro se encarga de descartar los que no son ofertas reales. Por eso conviene que la lista sea amplia:

```
junior
jr
trainee
desarrollador
developer
qa
tester
backend
frontend
full stack
devops
programador
```

### Cómo se arma cada vuelta

1. **Empleos** (HTTP, sin Chrome): búsquedas de `job_queries.txt` en la sección Empleos, solo avisos con
   Solicitud sencilla de las últimas 24 h. Si el formulario queda completo con datos verificados
   (`answers.py`), **la solicitud se envía**; si falta algo, se guarda en LinkedIn → Mis empleos → En curso.
2. **Búsquedas de publicaciones** de `channels.txt` ("enviar cv" + un término), todas, primero.
3. **Grupos y páginas de empresa**: 8 por vuelta, rotando.
4. **Feed**, al final.

Cada fuente se deja de scrollear cuando unas pocas lecturas seguidas no traen posts nuevos, y la
fuente por la que va la vuelta queda guardada: un reinicio retoma desde ahí. Si una vuelta no
encuentra nada, la pausa siguiente se duplica (tope 60 min).

Las ofertas aptas con email van a la cola de borradores ordenadas por relevancia (Python/QA/junior
primero, Java/.NET/PHP al final). Las aptas **sin email** quedan en la pestaña "Vacantes para
contactar por LinkedIn" del dashboard con un mensaje sugerido.

### Variables de entorno — `.env`

| Variable | Default | Qué hace |
|---|---|---|
| `CV_DIR` | `~/Documentos/ADRIEL/cv/2026-10_relanzamiento/02_cv` | Carpeta con los CVs (requerida) |
| `CHROME_HEADLESS` | `1` | `0` abre Chrome con ventana (para iniciar sesión) |
| `CHROME_PROFILE_DIR` | `~/.config/linkedin-job-finder/chrome-profile` | Perfil de Chrome del loop |
| `SCROLL_MINUTES` | `8` | Tope de minutos de feed por vuelta |
| `CHANNEL_SCROLL_MINUTES` | `2` | Tope de minutos por búsqueda, grupo o página |
| `PAUSE_MINUTES_MIN` / `PAUSE_MINUTES_MAX` | `8` / `15` | Pausa base entre vueltas |
| `DAILY_SEND_LIMIT` | `100` | Borradores de Gmail por día |
| `EASY_APPLY_DAILY_LIMIT` | `25` | Solicitudes sencillas enviadas solas por día (`0` = solo guardar) |
| `STATE_DIR` | `data/` | Estado, CSVs y logs |

### Archivos de `data/`

| Archivo | Contenido |
|---|---|
| `state.json` | Posts vistos (se olvidan a los 60 días), cola de borradores, progreso de la vuelta |
| `enviados.csv` | Borradores creados |
| `empleos_linkedin.csv` | Avisos de Empleos y qué pasó con su Solicitud sencilla (`enviada`, `guardada incompleta`…) |
| `contactar_linkedin.csv` | Vacantes aptas sin email, para escribir por LinkedIn |
| `job_finder.log` | Actividad (lo que muestra el dashboard), rota a los 2 MB |
| `audit.log` | Un renglón por post evaluado, con el motivo del descarte |
| `descartar.txt` | Emails a sacar de la cola a mano (uno por línea) |

## Notas importantes

- **Envía postulaciones**: las Solicitudes sencillas completas se envían solas (hasta
  `EASY_APPLY_DAILY_LIMIT` por día). Los mails nunca se envían: quedan como borradores en Gmail.
- **Verificación de seguridad**: si LinkedIn pide un checkpoint, el loop se frena; resolvelo con
  "Con ventana (login)" en el dashboard.
- **Recontacto**: a un mismo email no se le escribe dos veces por el mismo puesto, ni dos veces en 14 días.
- **Liviano en segundo plano**: corre con prioridad baja (`nice`/`ionice`), Chrome sin imágenes,
  video ni fuentes mientras scrollea, y el dashboard solo consulta cada 15 s con la pestaña visible.

## Construido con IA

Este proyecto fue diseñado y desarrollado en colaboración con **Claude** (Anthropic) como herramienta de productividad para la búsqueda de empleo. Desde la arquitectura del scraper hasta el sistema inteligente de análisis de patrones, cada decisión técnica fue iterada en conversación con IA para optimizar la detección de oportunidades laborales reales y minimizar falsos positivos.

## Autor

**Adriel Fabricio López**
Estudiante de Tecnicatura en Programación — UTN Córdoba, Argentina
