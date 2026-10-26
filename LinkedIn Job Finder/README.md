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

### Configuración — `config.py`

- `MIN_KEYWORDS_MATCH`: Cantidad mínima de keywords que debe tener un post para pasar el primer filtro (default: 1).

### Credenciales — `.env`

```
LINKEDIN_USER=tu_email@gmail.com
LINKEDIN_PASS=tu_contraseña
```

## Estructura del proyecto

```
linkedin_job_finder/
├── main.py           # Orquestador principal
├── scraper.py        # Scraping, análisis inteligente y verificación
├── config.py         # Configuración y carga de keywords
├── keywords.txt      # Palabras clave de búsqueda
├── requirements.txt  # Dependencias Python
├── .env.example      # Template de credenciales
├── .env              # Tus credenciales (no commitear)
├── .gitignore        # Archivos excluidos del repo
└── seen_posts.txt    # Registro de posts ya procesados (auto-generado)
```

## Notas importantes

- **Verificación de seguridad**: LinkedIn puede pedir un captcha la primera vez. El script pausa y te deja resolverlo manualmente antes de continuar.
- **Anti-detección**: El script incluye medidas para evitar la detección como bot (delays entre acciones, flags de Chrome, property overrides). No lo ejecutes muchas veces seguidas.
- **Sin duplicados**: Los posts procesados se guardan en `seen_posts.txt`. En la siguiente ejecución no se vuelven a analizar. Si querés empezar de cero, borrá ese archivo.
- **Solo lectura**: La herramienta no interactúa con las publicaciones, no envía mensajes ni realiza acciones en tu cuenta. Solo lee el feed y abre pestañas.

## Construido con IA

Este proyecto fue diseñado y desarrollado en colaboración con **Claude** (Anthropic) como herramienta de productividad para la búsqueda de empleo. Desde la arquitectura del scraper hasta el sistema inteligente de análisis de patrones, cada decisión técnica fue iterada en conversación con IA para optimizar la detección de oportunidades laborales reales y minimizar falsos positivos.

## Autor

**Adriel Fabricio López**
Estudiante de Tecnicatura en Programación — UTN Córdoba, Argentina
