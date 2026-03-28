# LinkedIn Job Finder

Scraper de LinkedIn Jobs con Django REST Framework + Selenium. Busca empleos remotos por keywords en LinkedIn Jobs Search y analiza el contenido para identificar ofertas reales.

## Arquitectura

```
Django 4.2 + DRF  ←→  REST API  ←→  Frontend SPA (index.html)
      ↓
ScraperService (Selenium + PyVirtualDisplay)
      ↓
LinkedIn Jobs Search (/jobs/search/?keywords=...&f_WT=2)
      ↓
JobAnalyzer (scoring) → PostgreSQL
      ↓
MailerService (SMTP Gmail)
```

### Modos de búsqueda

| Modo | Descripción |
|------|-------------|
| **Jobs Search** (default) | Busca directamente en `linkedin.com/jobs/search/` con la keyword como término de búsqueda. Filtro: remoto global (`f_WT=2`) + última semana (`f_TPR=r604800`) |
| **Feed Scan** (legacy) | Scrollea el feed general y filtra posts con keywords post-hoc |

## Requisitos

- Python 3.11+
- Docker + Docker Compose
- Variables de entorno (ver `.env.example`)

## Variables de entorno

Crear un archivo `.env` en la raíz basado en `.env.example`:

| Variable | Descripción | Requerida |
|---|---|---|
| `SECRET_KEY` | Django secret key | Sí |
| `LINKEDIN_USER` | Email de tu cuenta LinkedIn | Sí |
| `LINKEDIN_PASS` | Contraseña de LinkedIn | Sí |
| `GMAIL_USER` | Email de Gmail para enviar CVs | No |
| `GMAIL_APP_PASSWORD` | App password de Gmail | No |
| `CV_PATH` | Ruta al archivo PDF del CV | No |
| `DB_NAME` | Nombre de la base de datos | No (default: `linkedin_job_api`) |
| `DB_USER` | Usuario de PostgreSQL | No (default: `postgres`) |
| `DB_PASSWORD` | Contraseña de PostgreSQL | No (default: `postgres`) |

## Instalación y setup con Docker

```bash
# 1. Clonar el repo
git clone https://github.com/fabri404/LinkedIn-Job-Finder.git
cd LinkedIn-Job-Finder

# 2. Crear archivo de entorno
cp .env.example .env
# Editar .env con tus credenciales

# 3. Levantar en modo desarrollo
make up

# 4. Crear superusuario
make docker-shell
# dentro del shell:
# python manage.py createsuperuser
```

La app queda disponible en `http://localhost:8001`.

## Desarrollo local (sin Docker)

```bash
# Crear virtualenv
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Base de datos SQLite (solo dev)
python manage.py migrate --settings=config.settings.development

# Correr servidor
make run
```

## Correr tests

```bash
# Local
make test

# Con cobertura
make coverage

# En Docker
make docker-test
```

Cobertura actual: **90%** (160 tests)

## Comandos Docker

```bash
make up          # Levantar dev (db + web-dev con hot-reload)
make down        # Detener
make logs        # Ver logs de web-dev
make docker-migrate   # Correr migraciones
make docker-shell     # Shell de Django
make docker-test      # Tests en Docker
```

## API Endpoints

| Método | Endpoint | Descripción |
|--------|----------|-------------|
| `GET` | `/api/health/` | Health check |
| `POST` | `/api/auth/token/` | Obtener token de autenticación |
| `GET/POST` | `/api/keywords/` | Listar / crear keywords |
| `PATCH/DELETE` | `/api/keywords/{id}/` | Editar / eliminar keyword |
| `POST` | `/api/searches/start/` | Iniciar búsqueda (202 Accepted) |
| `GET` | `/api/searches/` | Listar sesiones de búsqueda |
| `GET` | `/api/searches/{id}/` | Detalle de sesión |
| `GET` | `/api/jobs/` | Listar empleos encontrados |
| `GET` | `/api/jobs/{id}/` | Detalle de empleo con score |
| `POST` | `/api/jobs/{id}/send-email/` | Enviar CV al reclutador |
| `GET/POST` | `/api/emails/` | Historial de emails enviados |

### Iniciar búsqueda

```bash
curl -X POST http://localhost:8001/api/searches/start/ \
  -H "Authorization: Token <tu_token>" \
  -H "Content-Type: application/json" \
  -d '{"search_mode": "jobs", "scroll_duration": 60}'
```

## Estructura del proyecto

```
linkedin-job-api/
├── apps/
│   ├── jobs/          # Scraper, modelos Job y SearchSession, API
│   ├── keywords/      # CRUD de keywords de búsqueda
│   └── mailer/        # Envío de CVs por email
├── config/
│   ├── settings/
│   │   ├── base.py
│   │   ├── development.py
│   │   └── production.py
│   ├── urls.py
│   └── views.py
├── templates/
│   └── index.html     # Frontend SPA
├── Dockerfile
├── docker-compose.yml
├── Makefile
└── requirements.txt
```
