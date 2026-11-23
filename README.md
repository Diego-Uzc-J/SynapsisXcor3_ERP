# 🏢 SynaXcor3_ERP

**Sistema ERP Modular Full-Stack** construido bajo una arquitectura de **Monolito Modular** (`FastAPI` + `PostgreSQL`) y una interfaz **SPA moderna** (`React` + `Vite` + `TypeScript`). Un ERP (Enterprise Resource Planning o Planificación de Recursos Empresariales) es un sistema de software para gestionar y centralizar los principales procesos de negocio de una organización.

[![Python](https://img.shields.io/badge/Python-3.15%2B-3776AB?logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-Backend-009688?logo=fastapi&logoColor=white)](https://tiangolo.com)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-18%2B-4169E1?logo=postgresql&logoColor=white)](https://postgresql.org)
[![React](https://img.shields.io/badge/React-19%2B-61DAFB?logo=react&logoColor=black)](https://react.dev)
[![TypeScript](https://img.shields.io/badge/TypeScript-5.8%2B-3178C6?logo=typescript&logoColor=white)](https://typescriptlang.org)
[![Vite](https://img.shields.io/badge/Vite-8%2B-646CFF?logo=vite&logoColor=white)](https://vite.dev)
[![Docker](https://img.shields.io/badge/Docker-Compose-2496ED?logo=docker&logoColor=white)](https://docker.com)

---

## 📋 Descripción General

**SynaXcor3_ERP** está diseñado para gestionar de forma integral las operaciones centrales de empresas medianas e industriales. Su enfoque de **monolito modular** garantiza un desacoplamiento estricto por dominios de negocio, facilitando el mantenimiento diario y permitiendo una futura migración hacia microservicios sin reescribir la lógica central.

El desarrollo del sistema sigue la metodología **Spec-Driven Development (SDD)**: cada funcionalidad nace a partir de contratos funcionales y técnicos ubicados en `specs/` antes de escribir código en el servidor o en el cliente.

### 🏗️ Arquitectura del Sistema

El diagrama resume la separación de responsabilidades entre el cliente web (**SPA Frontend**), el **Monolito Modular** en FastAPI gobernado por contratos **SDD** y seguridad **OWASP**, y la capa de persistencia y despliegue (**PostgreSQL 18+** y **Docker Compose**):

* **Frontend SPA (`React 19` + `Vite 8` + `TypeScript`):** Interfaz desacoplada con gestión de estado y caché en servidor (`TanStack Query v5` y `Zustand v5`), estilos con `Tailwind CSS v4` y enrutamiento protegido por roles (`React Router v7` con guardias RBAC).
* **Gobernanza SDD y Núcleo de Seguridad:** Especificaciones técnicas en `specs/` como fuente de verdad y capa transversal de seguridad (`Argon2id`, `JWT`, `CAPTCHA aritmético`, `require_roles` RBAC y rate limiting con `slowapi`).
* **Monolito Modular (`FastAPI` + `Python 3.15`):** Siete dominios aislados (`Users & Security`, `Inventory`, `Sales`, `Purchasing`, `Accounting`, `HR` y `Manufacturing`) construidos sobre `Pydantic v2`, `SQLAlchemy 2.1+` y `Alembic`.
* **Infraestructura y Datos:** Base de datos relacional **PostgreSQL 18+** orquestada localmente mediante **Docker Compose** junto a la API y la aplicación web.

![Arquitectura del sistema SynaXcor3_ERP](docs/images/arquitectura_sistema_erp.jpeg)

### 🧩 Módulos del Sistema
* 🔐 **Usuarios, Roles y Seguridad (`users`):** Autenticación JWT, CAPTCHA aritmético *stateless* y control de acceso basado en roles (RBAC) con protección Top OWASP.
* 📦 **Inventario y Logística (`inventory`):** Control de almacenes, stock en tiempo real y trazabilidad de movimientos.
* 💼 **Ventas y Facturación (`sales`):** Gestión comercial, cotizaciones, pedidos y emisión de facturas.
* 🛒 **Compras y Proveedores (`purchasing`):** Órdenes de compra, recepciones y gestión de abastecimiento.
* 📊 **Finanzas y Contabilidad (`accounting`):** Partida doble, asientos contables y reportes financieros.
* 👥 **Recursos Humanos (`hr`):** Gestión de empleados, contratos y nómina.
* 🏭 **Manufactura y Producción (`manufacturing`):** Listas de materiales (BOM), recetas y órdenes de producción.

---

## 🛠️ Stack Tecnológico

| Capa | Tecnologías Principales |
| :--- | :--- |
| **Backend** | Python 3.15+, FastAPI, SQLAlchemy 2.1+, Alembic, Pydantic v2, `uv`, Ruff, Pytest |
| **Seguridad** | `pwdlib[argon2]` (Argon2id), `PyJWT[crypto]`, `itsdangerous`, `slowapi` |
| **Frontend** | React 19+, Vite 8+, TypeScript 5.8+, TanStack Query v5, Zustand v5, Tailwind CSS v4, React Router v7, Vitest |
| **Base de Datos** | PostgreSQL 18+ (Producción) y SQLite (Desarrollo) |
| **Infraestructura** | Docker & Docker Compose |

---

## 📂 Estructura del Repositorio

```text
SynapsisXcor3_ERP/
├── .opencode/          # Reglas y configuración de asistencia IA (SDD y control de memoria)
├── specs/              # Especificaciones funcionales y técnicas por módulo (Contratos SDD)
├── memory/             # Bitácoras técnicas modulares
├── docs/               # Documentación técnica, diagramas y guías
├── backend/            # API REST en FastAPI (Monolito Modular)
│   ├── src/core/       # Configuración, base de datos y seguridad (JWT, Argon2id, RBAC)
│   ├── src/modules/    # Dominios aislados (models, schemas, services, router)
│   └── tests/          # Pruebas unitarias, de integración y seguridad (Pytest)
├── frontend/           # Aplicación web SPA en React + Vite + TypeScript
│   └── src/
│       ├── api/        # Clientes HTTP, interceptores y tipos sincronizados
│       ├── components/ # Componentes UI reutilizables
│       ├── layouts/    # Estructuras visuales y navegación
│       ├── modules/    # Vistas y lógica por dominio del ERP
│       ├── routes/     # Rutas y guardias RBAC
│       └── store/      # Estado global (Zustand)
├── docker-compose.yml  # Orquestación local de PostgreSQL, API y Web
├── memory_protocol.md  # Reglas de actualización de memoria técnica
├── MEMORY.md           # Registro vivo del estado del sistema y decisiones técnicas
└── PROJECT_MANIFEST.md # Manifiesto completo de arquitectura y gobierno
```

---

## 🚀 Inicio Rápido

### Prerrequisitos
* [Docker](https://docker.com) y **Docker Compose** instalados.
* *(Opcional para ejecución local sin contenedores)* Python 3.15+, `uv` y Node.js 22+.

### Opción 1: Levantar todo el entorno con Docker (Recomendado)

1. **Clonar el repositorio:**
   ```bash
   git clone https://github.com/Diego-Uzc-J/SynapsisXcor3_ERP.git
   cd SynapsisXcor3_ERP
   ```

2. **Construir y levantar los contenedores (Base de datos, Backend y Frontend):**
   ```bash
   docker compose up --build -d
   ```

3. **Aplicar las migraciones iniciales de la base de datos:**
   ```bash
   docker compose exec api alembic upgrade head
   ```

4. **Detener los servicios cuando finalices:**
   ```bash
   docker compose down
   ```

---

### Opción 2: Ejecución en Entorno Local

1. **Levantar únicamente la base de datos PostgreSQL:**
   ```bash
   docker compose up -d db
   ```

2. **Iniciar el Backend (Terminal 1):**
   ```bash
   cd backend
   uv sync
   source .venv/bin/activate  # En Windows: .venv\Scripts\activate
   export DATABASE_URL="postgresql://erp_user:erp_password@localhost:5432/erp_database"
   alembic upgrade head
   uvicorn src.main:app --reload --port 8000
   ```

3. **Iniciar el Frontend (Terminal 2):**
   ```bash
   cd frontend
   npm install
   npm run dev
   ```

---

## 🌐 Accesos Locales

Una vez levantados los servicios, puedes ingresar a las siguientes direcciones:

* 🖥️ **Aplicación Web (Frontend):** [http://localhost:5173](http://localhost:5173)
* 📘 **Documentación API (Swagger UI):** [http://localhost:8000/docs](http://localhost:8000/docs)
* 📗 **Documentación API (ReDoc):** [http://localhost:8000/redoc](http://localhost:8000/redoc)

---

## 🧪 Pruebas y Calidad

El proyecto combina pruebas automatizadas en backend y frontend para validar reglas de negocio, seguridad y regresión:

* **Backend (`pytest`):** Verifica contratos de dominio, transacciones ACID, control de estados/inmutabilidad, seguridad OWASP/RBAC y escenarios BDD por módulo.
```bash
  cd backend
  pytest
```

* **Frontend (Vitest):** Valida componentes y lógica de cliente con TypeScript estricto.   
```Bash
cd frontend
npm test
```


---

## 📐 Reglas de Arquitectura y Contribución

1. **Spec-Driven Development:** Todo cambio funcional debe estar respaldado por su especificación correspondiente en la carpeta `specs/`.
2. **Integridad ACID e Inmutabilidad:** Las operaciones entre módulos son atómicas; los asientos contables publicados (`POSTED`), facturas emitidas y movimientos históricos de inventario son inmutables.
3. **Memoria Viva:** Cualquier modificación en `backend/` o `frontend/` debe documentarse en `MEMORY.md` antes de realizar el commit.
4. **Estándar de Commits:** Se recomienda utilizar [Conventional Commits](https://conventionalcommits.org) (ej. `feat(inventory): ...`, `fix(sales): ...`).

---

## 📚 Documentación y Guías

* 🗄️ **Base de Datos y Migraciones:** Configuración de PostgreSQL, Docker Compose y uso de Alembic. — [Ver guía de base de datos](docs/database_setup.md)
* 🔐 **Diagramas de Usuarios y Roles (`users`):** Arquitectura y flujos del módulo de usuarios y roles. — [Ver diagramas](docs/users_diagrams.md)
* 📦 **Diagramas de Inventario (`inventory`):** Arquitectura y flujos del módulo de inventario. — [Ver diagramas](docs/inventory_diagrams.md)
* 💼 **Diagramas de Ventas y Facturación (`sales`):** Arquitectura y flujos del módulo de ventas y facturación. — [Ver diagramas](docs/sales_diagrams.md)
* 🛒 **Diagramas de Compras y Proveedores (`purchasing`):** Arquitectura y flujos del módulo Compras. — [Ver diagramas](docs/purchasing_diagrams.md)
* 📊 **Diagramas de Finanzas y Contabilidad (`accounting`):** Arquitectura y flujos del módulo Contabilidad. — [Ver diagramas](docs/accounting_diagrams.md)
* 👥 **Diagramas de Recursos Humanos (`hr`):** Arquitectura y flujos del módulo Recursos Humanos. — [Ver diagramas](docs/hr_diagrams.md)
* 🏭 **Diagramas de Manufactura y Producción (`manufacturing`):** Arquitectura y flujos del módulo Manufactura y Producción. — [Ver diagramas](docs/manufacturing_diagrams.md)


---
*Creado por Ing. Diego A. Uzcátegui J. | www.linkedin.com/in/diego-uzc-j | Portafolio Profesional*
