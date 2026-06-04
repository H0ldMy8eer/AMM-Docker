# AMM-Docker (Automated Monolith Migration to Docker)

Инструментальное средство для автоматизированной контейнеризации монолитных приложений на Python и Java с поддержкой фронтенд-фреймворков. Проект разрабатывается в рамках выпускной квалификационной работы (ВКР).

## Описание проекта

Цель системы — упростить процесс миграции устаревших монолитных систем на микросервисную архитектуру путём автоматической генерации Docker-артефактов (`Dockerfile`, `docker-compose.yaml`, `nginx.conf`) на основе статического анализа структуры исходного кода.

Инструмент поддерживает **три класса монолитов**:
- **Python-бэкенд** — Flask, FastAPI, Django, Starlette, Sanic
- **Java-бэкенд** — Spring Boot (Maven / Gradle / Gradle KTS)
- **Фронтенд** — React, Next.js, Vue, Nuxt, Angular, Svelte

## Технологический стек

| Компонент | Технология |
|---|---|
| Core | Python 3.10+ |
| Анализ Python | AST-сканер (`scanner.py`) — Blueprint, APIRouter, urlpatterns |
| Анализ Java | Regex-сканер (`java_scanner.py`) — pom.xml, build.gradle, application.properties/yml |
| Анализ фронтенда | `frontend_scanner.py` — package.json, vite.config, angular.json, next.config.js |
| Шаблонизация | Jinja2 |
| Контейнеризация | Docker, Docker Compose |
| API Gateway | Nginx |
| Логирование | Grafana + Loki + Promtail |
| GUI | CustomTkinter |

## Поддерживаемые фреймворки

### Python-бэкенд

| Фреймворк | Что детектируется |
|---|---|
| **Flask** | `Blueprint`, `url_prefix`, `create_app()`, Flask-расширения |
| **FastAPI** | `APIRouter`, `prefix`, `include_router` |
| **Django** | `urlpatterns`, `include()`, `path()` |
| **Starlette / Sanic** | Базовая структура маршрутов |

### Java-бэкенд (Spring Boot)

| Сборщик | Что детектируется |
|---|---|
| **Maven** | `pom.xml` → версия Spring Boot, Java, зависимости (JPA, Security, Web, Actuator, ...) |
| **Gradle** | `build.gradle` + **Kotlin DSL** (`.gradle.kts`) → плагины, версии, зависимости |

Дополнительно определяются:
- Архитектура: **layered** (`controller/service/repository`) vs **domain-driven** (`auth/product/order`)
- Аннотации: `@RestController`, `@Service`, `@Repository`, `@Entity`
- Конфигурация: `application.properties` / `application.yml` — порт, URL БД, имя приложения

### Фронтенд

| Фреймворк | Dockerfile-стратегия |
|---|---|
| **React** (Vite / CRA) | builder → `nginx:alpine` со статикой |
| **Vue** (Vite / Vue CLI) | builder → `nginx:alpine` со статикой |
| **Angular** (Angular CLI) | builder → `nginx:alpine` (dist/`<name>`/browser/) |
| **Svelte** (Vite) | builder → `nginx:alpine` со статикой |
| **Next.js** | builder → `node:alpine` standalone-сервер (не nginx) |
| **Nuxt** | builder → `nginx:alpine` (.output/public/) |

Детектируется менеджер пакетов: **npm / yarn / pnpm** (по lock-файлу).

## Архитектура после миграции

```
                    ┌─────────────────────────────────────────┐
  Browser  ──────▶  │  Nginx Gateway  :8888                   │
                    │  /api  ──▶  backend (Java :8080)        │
                    │  /     ──▶  frontend (React :80)        │
                    └─────────────────────────────────────────┘
                           │              │
                    ┌──────┘     ┌────────┘
                    ▼            ▼
              [backend]     [frontend]
              Spring Boot   nginx+React
                    │
                    ▼
              [postgres :5432]
                    │
              [loki + promtail]
                    │
              [grafana :3001]
```

- **Изоляция:** каждый модуль/сервис получает собственный контейнер и `Dockerfile`.
- **Сетевое взаимодействие:** все сервисы в сети `app-network`.
- **Маршрутизация:** Nginx (порт 8888) → по `url_prefix`.
- **База данных:** PostgreSQL с персистентным Docker Volume (`postgres_data`).

## Ключевые возможности

### Автодекомпозиция (Python / Flask)

Если в монолите несколько `Blueprint`-определений — сканер создаёт отдельный микросервис для каждого, с уникальным `url_prefix`. Каждый сервис получает:
- `run.py` с поддержкой `create_app()` / прямого `app`-объекта
- `requirements.txt` (фильтрация зависимостей по коду)
- Стабы для импортов из других сервисов

### Многоступенчатые Dockerfile (Java / Frontend)

- **Java:** `maven:3.9-alpine` или `gradle:8-jdk-alpine` → `eclipse-temurin:jre-alpine` (только JRE в продакшне)
- **SPA:** `node:alpine` (build) → `nginx:1.27-alpine` (serve)
- **Next.js:** `node:alpine` (build) → `node:alpine` (standalone runtime)

### Умный entrypoint (Python)

Каждый Python-сервис запускается через `run.py`, который:
1. Ищет оригинальный `create_app()` или `app`-объект
2. При неудаче — создаёт Flask-приложение самостоятельно
3. Инициализирует расширения из `extensions.py`
4. Регистрирует Blueprint с `url_prefix`
5. Создаёт таблицы БД через `db.create_all()`

### Безопасность

- `.env` генерируется со случайным `POSTGRES_PASSWORD` и `SECRET_KEY`
- Рядом создаётся `.env.example` с заглушками

## Инструкция по запуску

### 1. Подготовка

Поместите исходный монолит в рабочую директорию.

### 2. Сканирование и генерация (GUI)

```bash
python main_gui.py
```

Укажите путь к монолиту и нажмите **«Генерировать»**. Результат появится в папке `docker_out/`.

### 3. Развёртывание

```bash
cd docker_out
docker compose up --build
```

### 4. Проверка

- Nginx Gateway: `http://localhost:8888`
- Grafana (логи): `http://localhost:3001`
- Прямой порт Java-бэкенда: `http://localhost:8080`
- Прямые порты Python-сервисов: начиная с `5001`, `5002`, ...

### 5. Остановка и сброс

Через GUI:
- **«Stop Containers»** — `docker compose down` (volume с данными сохраняется)
- **«Удалить docker_out + БД»** — останавливает контейнеры, удаляет volume и папку `docker_out`

## Структура проекта

```
AMM-Docker/
├── main_gui.py                    # GUI-приложение (CustomTkinter)
├── src/
│   ├── scanner.py                 # AST-анализ Python-монолита
│   ├── java_scanner.py            # Анализ Java/Spring Boot (Maven, Gradle, KTS)
│   ├── frontend_scanner.py        # Анализ фронтенда (React, Next.js, Vue, Angular, ...)
│   └── generator.py               # Генератор Docker-артефактов (Python + Java + Frontend)
├── templates/
│   ├── Dockerfile.java-maven.jinja2   # 2-stage Maven → JRE
│   ├── Dockerfile.java-gradle.jinja2  # 2-stage Gradle → JRE
│   ├── Dockerfile.frontend.jinja2     # SPA/Next.js Dockerfile
│   ├── entrypoint.jinja2              # run.py для Python-сервисов
│   ├── docker-compose.jinja2
│   ├── nginx.conf.jinja2
│   └── api_bridge.jinja2
├── tests/
│   ├── test_scanner.py            # Тесты Python AST-сканера
│   ├── test_templates.py          # Тесты Jinja2-шаблонов
│   ├── test_java_scanner.py       # Тесты Java-сканера (~80 тестов)
│   └── test_frontend_scanner.py   # Тесты фронтенд-сканера (~93 теста)
└── docker_out/                    # Генерируется автоматически
    ├── .env
    ├── .env.example
    ├── docker-compose.yaml
    ├── nginx/nginx.conf
    ├── logging/
    └── <service_name>/
        ├── Dockerfile
        └── <source_code>/
```

## Тесты

```bash
pytest tests/ -v
```

Всего ~209 тестов:

| Файл | Тестов | Покрытие |
|---|---|---|
| `test_scanner.py` | ~36 | Python AST-сканер |
| `test_templates.py` | ~34 | Jinja2-шаблоны (nginx, compose, Dockerfile) |
| `test_java_scanner.py` | ~80 | Maven, Gradle, KTS, архитектура, аннотации |
| `test_frontend_scanner.py` | ~93 | React, Next.js, Vue, Angular, Svelte, прокси |

## Статус ВКР

- [x] Python AST-анализатор структуры проекта (Flask, FastAPI, Django)
- [x] Java-анализатор (Spring Boot, Maven, Gradle, Kotlin DSL)
- [x] Фронтенд-анализатор (React, Next.js, Vue, Nuxt, Angular, Svelte)
- [x] Автодекомпозиция по Blueprint-определениям
- [x] Генератор Docker-инфраструктуры (Python, Java, Frontend)
- [x] Многоступенчатые Dockerfile (JRE-slim, nginx, node-standalone)
- [x] Механизм автоматических заглушек (Stubs) для Python
- [x] Оркестрация через Docker Compose
- [x] Nginx API Gateway с поддержкой `url_prefix`
- [x] Персистентное хранение данных PostgreSQL (Docker Volume)
- [x] Умный entrypoint с поддержкой `create_app()` factory
- [x] Автоматическая инициализация Flask-расширений
- [x] Генерация `.env` со случайными секретами
- [x] Распределённое логирование (Grafana + Loki + Promtail)
- [x] Визуализация карты зависимостей
- [x] GUI-кнопка полного сброса окружения
