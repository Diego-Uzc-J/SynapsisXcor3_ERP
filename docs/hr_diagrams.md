# Diagramas técnicos — Módulo `hr`

Documentación visual del módulo de Recursos Humanos y Nómina, derivada de
`specs/hr_spec.md`, de `PROJECT_MANIFEST.md` (rol RBAC `HR`) y del código final
de `backend/src/modules/hr/`, `backend/src/modules/accounting/service.py` y
`frontend/src/modules/hr/`.

| Diagrama | Qué responde |
| --- | --- |
| Clases | Qué entidades SQLAlchemy existen, sus enums, relaciones y servicios de dominio |
| Componentes | Cómo viaja una petición desde React y TanStack Query hasta PostgreSQL y la contabilización atómica |
| Secuencia | Qué ocurre al generar un periodo de nómina y al aprobarlo con asiento contable |

> **Convención de nombres.** La spec usa `PayrollStatus` para el ciclo
> `DRAFT`/`APPROVED`/`PAID`. En el código se materializa como `PayrollRunStatus`
> (enum nativo `payroll_run_status`). El diagrama conserva el nombre solicitado
> y muestra el mapeo al contrato real, igual que `docs/accounting_diagrams.md`.
> La regla 5 de la spec nombra los roles `HR` y `ADMINISTRATOR`; en el router se
> declara `require_hr = require_roles([RoleEnum.HR])` y el administrador entra
> por el *bypass* de superusuario de `core/security.py`.

---

## 1. Diagrama de clases

Entidades SQLAlchemy de `models.py`, enums de estado/tipo, cardinalidades y los
métodos clave de `service.py`. `Decimal` significa `Numeric(14, 2)` (`MONEY`) o
`Numeric(7, 2)` (`HOURS`) en PostgreSQL y viaja como cadena en la API.

```mermaid
classDiagram
    class Base {
        <<abstract>>
        +metadata
    }

    class ContractType {
        <<enumeration>>
        INDEFINITE
        FIXED_TERM
        SERVICES
        PART_TIME
    }

    class AttendanceStatus {
        <<enumeration>>
        PRESENT
        ABSENT
        SICK_LEAVE
        VACATION
        OVERTIME
    }

    class PayrollStatus {
        <<enumeration>>
        DRAFT
        APPROVED
        PAID
    }

    class PayrollRunStatus {
        <<enumeration>>
        DRAFT
        APPROVED
        PAID
    }

    class Employee {
        +int id PK
        +str identification_number UK
        +str first_name
        +str last_name
        +str email
        +str phone nullable
        +date birth_date
        +date hire_date
        +bool is_active
        +datetime created_at
        +list~Contract~ contracts
        +list~Attendance~ attendance_records
        +list~Payslip~ payslips
    }

    class Contract {
        +int id PK
        +int employee_id FK
        +ContractType contract_type
        +Decimal base_salary MONEY
        +date start_date
        +date end_date nullable
        +bool is_active
        +Employee employee
    }

    class Attendance {
        +int id PK
        +int employee_id FK
        +date date
        +AttendanceStatus status
        +Decimal overtime_hours HOURS
        +str notes nullable
        +Employee employee
    }

    class PayrollRun {
        +int id PK
        +str code UK
        +date period_start
        +date period_end
        +PayrollStatus status
        +bool is_adjustment
        +Decimal total_earnings MONEY
        +Decimal total_deductions MONEY
        +Decimal total_net MONEY
        +datetime approved_at nullable
        +datetime created_at
        +list~Payslip~ payslips
    }

    class Payslip {
        +int id PK
        +int payroll_run_id FK
        +int employee_id FK
        +Decimal base_salary MONEY
        +Decimal overtime_pay MONEY
        +Decimal bonuses MONEY
        +Decimal deductions MONEY
        +Decimal earnings MONEY
        +Decimal net_pay MONEY
        +PayrollRun payroll_run
        +Employee employee
    }

    class HRService {
        <<service>>
        +create_employee(db, data) Employee
        +get_employee(db, employee_id) Employee
        +update_employee(db, employee_id, data) Employee
        +create_contract(db, data) Contract
        +get_active_contract(db, employee_id) Contract
        +create_attendance(db, data) Attendance
        +create_payroll_run(db, data) PayrollRun
        +_eligible_payroll_employees(db, start, end) list
        +_overtime_hours_by_employee(db, ids, start, end) dict
        +_build_payslips(db, run, period, bonuses, deductions) list
        +_set_payroll_totals(run, payslips) None
        +recalculate_payroll_run(db, run_id) PayrollRun
        +set_payroll_run_status(db, run_id, status) PayrollRun
        +_ensure_payroll_mutable(run) None
        +_ensure_payroll_postable(run) tuple
        +approve_payroll_run(db, run_id) PayrollRun
        +_atomic(db) Iterator
    }

    class AccountingService {
        <<service>>
        +post_payroll_run_accounting(db, code, date, totals, commit) AccountingResult
        +_resolve_account_id(db, role, override) int
        +_build_posted_entry(db, data) JournalEntry
        +_find_generated_entry(db, reference, label) JournalEntry
        +_unit_of_work(db, commit) Iterator
    }

    Base <|-- Employee
    Base <|-- Contract
    Base <|-- Attendance
    Base <|-- PayrollRun
    Base <|-- Payslip

    Employee "1" --> "0..*" Contract : contracts
    Employee "1" --> "0..*" Attendance : attendance_records
    Employee "1" --> "0..*" Payslip : payslips
    PayrollRun "1" *-- "0..*" Payslip : payslips

    Contract ..> ContractType : contract_type
    Attendance ..> AttendanceStatus : status
    PayrollRun ..> PayrollStatus : status
    PayrollStatus ..> PayrollRunStatus : se materializa como

    HRService ..> Employee : alta y perfil
    HRService ..> Contract : contrato activo unico con FOR UPDATE
    HRService ..> Attendance : horas extra del periodo
    HRService ..> PayrollRun : DRAFT APPROVED PAID
    HRService ..> Payslip : devengos deducciones neto
    HRService ..> PayrollStatus : inmutabilidad APPROVED PAID
    HRService ..> AccountingService : post_payroll_run_accounting commit false
    AccountingService ..> PayrollRun : reference_document = code
```

### Reglas reflejadas en el modelo

- **Contrato activo único.** `create_contract` bloquea la fila del empleado con
  `SELECT ... FOR UPDATE` y rechaza un segundo contrato vigente con
  `ActiveContractError` (400). `_find_active_contract` y `get_active_contract`
  son la base del cálculo de nómina.
- **Cálculo exacto.** `_build_payslips` usa solo `Decimal` con
  `ROUND_HALF_UP`: `base_salary = salario * min(días_del_periodo, 30) / 30`,
  `overtime_pay = horas_extra * salario / (30 * 8)`,
  `earnings = base_salary + overtime_pay + bonuses` y
  `net_pay = earnings - deductions`. `_set_payroll_totals` suma los importes ya
  cuantizados, por lo que los totales del encabezado coinciden con los
  desprendibles.
- **Empleados elegibles.** `_eligible_payroll_employees` exige
  `Employee.is_active = True` y `Contract.is_active = True` con
  `start_date <= period_end` y (`end_date IS NULL` o `end_date >= period_start`).
  Las horas extra se suman de `Attendance` del rango con
  `_overtime_hours_by_employee`.
- **Inmutabilidad.** `_ensure_payroll_mutable` lanza
  `ImmutablePayrollRunError` (409) en `APPROVED`/`PAID` antes de recalcular,
  cambiar el estado o aprobar. La corrección exige un nuevo `PayrollRun` con
  `is_adjustment = True`. `set_payroll_run_status` solo permite `DRAFT → PAID`.
- **Aprobación contable.** `approve_payroll_run` valida con
  `_ensure_payroll_postable` (desprendibles, devengado positivo y totales
  coherentes) y llama a `post_payroll_run_accounting(..., commit=False)`, de modo
  que asiento y cambio de estado comparten una sola unidad de trabajo.
- **Integridad en base de datos.** `identification_number` y `code` son únicos;
  `Payslip` es único por `(payroll_run_id, employee_id)`. Las FK usan
  `RESTRICT` salvo `payroll_runs → payslips`, que usa `CASCADE`. Los `CHECK`
  garantizan fechas coherentes, importes no negativos y
  `net_pay = earnings - deductions` / `total_net = total_earnings - total_deductions`.

---

## 2. Diagrama de componentes

Arquitectura full-stack: vistas React → guardias RBAC → hooks de TanStack Query
y cliente HTTP → routers, esquemas y servicios de FastAPI → tablas PostgreSQL,
con la integración contable atómica en `accounting`.

```mermaid
flowchart TB
    subgraph CLIENTE["Frontend React 19 + Vite"]
        direction TB
        USR["Usuario con rol hr o administrator"]
        ROUTES["routes/index.tsx<br/>hr redirige a employees<br/>employees contracts attendance payrolls"]
        GUARD["routes/guards.tsx<br/>RequireModule module hr<br/>RequireRole hr administrator"]
        V_EMP["EmployeeList EmployeeProfile EmployeeForm"]
        V_CON["ContractsPage ContractForm<br/>active_only true e historial inactivo"]
        V_ATT["AttendancePage AttendanceForm<br/>filtros empleado fecha periodo"]
        V_PAY["PayrollRunsPage PayrollRunDetail PayrollRunForm<br/>generacion DRAFT y aprobacion"]
        SHARED["HrTabs StatusBadge HrDialog<br/>constants format errors"]
        CACHE["Vistas activas y detalle<br/>refetch tras mutacion"]
    end

    subgraph DATA["Capa de datos del cliente"]
        direction TB
        HOOKS["hooks.ts<br/>useEmployees useEmployee useContractsByEmployee<br/>useAttendance usePayrollRuns usePayrollRun<br/>useCreateEmployee useUpdateEmployee useCreateContract<br/>useCreateAttendance useCreatePayrollRun useApprovePayrollRun"]
        KEYS["api.ts hrKeys<br/>employees contracts attendance payrolls<br/>list detail byEmployee"]
        HTTP["api.ts + api/client.ts<br/>apiRequest Bearer buildQuery<br/>HrApiError 400 401 403 404 409 422"]
        FORMAT["types.ts y format.ts<br/>Decimal como string<br/>moneyString hoursString"]
    end

    subgraph API["API FastAPI /api/v1/hr"]
        direction TB
        RBAC["require_hr<br/>require_roles HR<br/>ADMINISTRATOR bypass"]
        ROUTERS["router.py<br/>employees contracts attendance payrolls<br/>11 endpoints POST GET PATCH"]
        SCHEMAS["schemas.py Pydantic v2<br/>EmployeeCreate ContractCreate AttendanceCreate<br/>PayrollRunCreate StrictMoney StrictHours<br/>extra forbid"]
        SERVICES["service.py<br/>contrato activo unico con FOR UPDATE<br/>_eligible_payroll_employees _build_payslips<br/>_ensure_payroll_mutable _ensure_payroll_postable<br/>approve_payroll_run con _atomic"]
        MODELS["models.py SQLAlchemy 2.x<br/>Mapped mapped_column CHECK FK"]
        ERR["hr_exception_handler<br/>HRServiceError a HTTP 400 404 409"]
    end

    subgraph ACC["Integracion contable atomica"]
        direction TB
        POST_ACC["accounting.services<br/>post_payroll_run_accounting commit false<br/>partida doble y _unit_of_work"]
        ASIENTO["JournalEntry POSTED<br/>ASI-NOM-YYYY-XXXX<br/>reference_document = PayrollRun.code"]
        CUENTAS["PUC cuentas activas<br/>expense 5100 payable 220505<br/>deductions por defecto payable"]
        PERIODO["accounting_periods<br/>is_closed false"]
    end

    subgraph DB["PostgreSQL"]
        direction TB
        T_EMP["employees"]
        T_CON["contracts"]
        T_ATT["attendance"]
        T_RUN["payroll_runs"]
        T_PAY["payslips"]
        T_ENUM["enum contract_type attendance_status payroll_run_status"]
        T_JE["journal_entries y journal_items"]
        T_ACC["accounts y accounting_periods"]
    end

    USR --> ROUTES
    ROUTES --> GUARD
    GUARD --> V_EMP
    GUARD --> V_CON
    GUARD --> V_ATT
    GUARD --> V_PAY
    V_EMP --> SHARED
    V_CON --> SHARED
    V_ATT --> SHARED
    V_PAY --> SHARED

    V_EMP -->|"useEmployees useEmployee mutaciones"| HOOKS
    V_CON -->|"useContractsByEmployee useCreateContract"| HOOKS
    V_ATT -->|"useAttendance useCreateAttendance"| HOOKS
    V_PAY -->|"usePayrollRuns useCreatePayrollRun useApprovePayrollRun"| HOOKS
    FORMAT --> HOOKS
    HOOKS --> KEYS
    HOOKS --> HTTP

    HTTP -->|"GET POST PATCH bajo api v1"| ROUTERS
    ROUTERS --> RBAC
    ROUTERS -->|"payload JSON snake_case"| SCHEMAS
    SCHEMAS -->|"datos validados Decimal como string"| SERVICES
    SERVICES --> MODELS
    ROUTERS -->|"errores de dominio"| ERR
    ERR -->|"detail 400 404 409"| HTTP
    HTTP -->|"JSON tipado Decimal como string"| HOOKS
    HOOKS -->|"invalida hrKeys y detalle"| CACHE

    SERVICES -->|"commit false en la misma transaccion"| POST_ACC
    POST_ACC --> CUENTAS
    POST_ACC --> PERIODO
    POST_ACC -->|"INSERT asiento POSTED"| ASIENTO
    ASIENTO --> T_JE
    CUENTAS --> T_ACC
    PERIODO --> T_ACC

    MODELS --> T_EMP
    MODELS --> T_CON
    MODELS --> T_ATT
    MODELS --> T_RUN
    MODELS --> T_PAY
    MODELS --> T_ENUM
```

### Lectura del diagrama

- **Doble guardia RBAC.** `RequireModule module="hr"` valida
  `allowed_modules` y `RequireRole roles={["hr","administrator"]}` refleja
  `require_hr = require_roles([RoleEnum.HR])` con bypass de administrador en el
  backend. Sin token, `apiRequest` recibe 401; con otro rol, 403.
- **Una sola capa de datos.** Ninguna vista llama a `fetch`: consumen
  `hooks.ts`, que delega en `api.ts` y comparte `hrKeys` para invalidar
  empleados, contratos, asistencia y nómina tras cada mutación.
- **Decimales como cadena.** `types.ts` y `format.ts` normalizan importes y horas
  con `moneyString`/`hoursString`; `StrictMoney`/`StrictHours` rechazan `float`
  con 422 y `extra="forbid"` bloquea campos no declarados.
- **Autoridad en el servidor.** El formulario de contratos consulta
  `active_only=true` para avisar de un contrato vigente, pero es
  `create_contract` con `FOR UPDATE` quien impide el segundo activo (400).
- **Integración real, no planificada.** A diferencia del diagrama de
  `accounting`, aquí `hr → accounting` es una arista sólida:
  `post_payroll_run_accounting(..., commit=False)` se ejecuta dentro de la
  transacción de RRHH, con cuentas activas y periodo abierto.
- **ACID en el servicio.** `hr._atomic` agrupa el `PayrollRun`, sus `Payslip` y
  el asiento `ASI-NOM`; `accounting._unit_of_work` no hace `COMMIT` propio cuando
  recibe `commit=False`. Cualquier excepción produce `ROLLBACK` completo.

---

## 3. Diagrama de secuencia — generación y aprobación de nómina

Flujo completo para `POST /api/v1/hr/payrolls` y
`POST /api/v1/hr/payrolls/{id}/approve`. Incluye contrato activo, cálculo de
`Payslip`, inmutabilidad de `APPROVED`/`PAID`, transacción ACID, asiento
contable y rollback ante fallo.

```mermaid
sequenceDiagram
    autonumber
    actor Op as Usuario HR
    participant UI as Vistas React
    participant Q as TanStack Query
    participant R as Router y Pydantic
    participant S as hr.services
    participant A as accounting.services
    participant DB as PostgreSQL

    Note over Op,DB: Generacion de periodo POST /api/v1/hr/payrolls

    Op->>UI: Generar nomina en PayrollRunsPage
    UI->>Q: useCreatePayrollRun payload
    Q->>R: POST /api/v1/hr/payrolls
    R->>R: require_hr con bypass ADMINISTRATOR
    R->>R: PayrollRunCreate StrictMoney code unico
    R->>S: create_payroll_run db data
    S->>S: _ensure_payroll_period y _ensure_unique_payroll_code
    alt Codigo duplicado o payload invalido
        S--xR: DuplicatePayrollCodeError o InvalidPayrollDataError
        R--xQ: 400 o 422 con detail
        Q--xUI: errorHint
        UI--xOp: Aviso de codigo duplicado
    else Periodo valido
        Note over S,DB: ACID un bloque _atomic para periodo y desprendibles
        S->>DB: INSERT payroll_runs status DRAFT
        S->>DB: SELECT employees join contracts activos y vigentes
        alt Empleado inactivo o contrato no vigente
            S->>S: _eligible_payroll_employees lo excluye
            Note over S: Sin Payslip para ese empleado escenario 6
        else Contrato activo vigente
            S->>DB: SELECT attendance del rango y suma overtime_hours
            S->>S: _build_payslips con Decimal ROUND_HALF_UP
            S->>S: base salario por min dias 30 sobre 30
            S->>S: horas extra por salario sobre 30 por 8
            S->>S: earnings mas bonuses menos deductions igual net_pay
            S->>DB: INSERT payslips y _set_payroll_totals
        end
        S->>DB: COMMIT
        S-->>R: PayrollRunResponse 201 con totales
        R-->>Q: 201 JSON
        Q->>Q: invalida hrKeys payrolls
        Q-->>UI: Periodo DRAFT con desprendibles
        UI-->>Op: Badge DRAFT y detalle
    end

    Note over Op,DB: Aprobacion POST /api/v1/hr/payrolls/id/approve

    Op->>UI: Aprobar periodo desde PayrollRunDetail
    UI->>Q: useApprovePayrollRun payrollRunId
    Q->>R: POST /api/v1/hr/payrolls/id/approve
    R->>R: require_hr y path id mayor que cero
    R->>S: approve_payroll_run db payroll_run_id
    S->>DB: SELECT payroll_runs con payslips
    S->>S: _ensure_payroll_mutable exige DRAFT

    alt Estado APPROVED o PAID
        S--xR: ImmutablePayrollRunError 409
        R--xQ: ApiError 409 con detail
        Q--xUI: errorHint de nomina de ajuste
        UI--xOp: Aviso de usar is_adjustment true
    else Estado DRAFT
        S->>S: _ensure_payroll_postable exige payslips y totales coherentes
        Note over S,DB: ACID una sola transaccion para asiento y estado
        S->>DB: SELECT payroll_runs con FOR UPDATE
        S->>S: repite validaciones de estado y totales
        S->>A: post_payroll_run_accounting commit false
        A->>A: valida Decimal partida doble e idempotencia por code
        A->>DB: SELECT accounts activas expense y payable
        A->>DB: SELECT accounting_periods con is_closed false
        alt PUC incompleto periodo cerrado o fallo contable
            A--xS: excepcion de dominio de accounting
            S->>DB: ROLLBACK sin asiento ni cambio de estado
            S--xR: PayrollAccountingError 400
            R--xQ: ApiError 400 con detail
            Q--xUI: errorHint de contabilizacion
            UI--xOp: Periodo sigue DRAFT sin asiento
        else Contabilizacion correcta
            A->>DB: INSERT journal_entries POSTED ASI-NOM
            A->>DB: INSERT journal_items debe gasto haber CxP y deducciones
            A-->>S: AccountingResult con entry POSTED
            S->>DB: UPDATE payroll_runs status APPROVED approved_at now
            S->>DB: COMMIT
            S-->>R: PayrollRunResponse APPROVED
            R-->>Q: 200 JSON
            Q->>Q: invalida payrolls y detalle
            Q-->>UI: Estado APPROVED
            UI-->>Op: Badge APPROVED y asiento trazable
        end
    end

    Note over UI,DB: APPROVED y PAID no se modifican correcciones con is_adjustment true
```

### Puntos críticos del flujo

- **Orden de validación.** Periodo y código antes de insertar; elegibilidad del
  contrato antes de calcular; estado mutable y totales coherentes antes de
  contabilizar. Ningún fallo deja filas parciales.
- **Elegibilidad real.** Se excluyen empleados inactivos, sin contrato activo o
  con contrato que no cubre el periodo (escenario 6). Las horas extra se leen de
  `Attendance` dentro del rango, no solo de registros `OVERTIME`.
- **Bloqueo y revalidación.** La aprobación vuelve a leer con
  `SELECT ... FOR UPDATE` y repite `_ensure_payroll_mutable` y
  `_ensure_payroll_postable`, evitando aprobaciones concurrentes o basadas en
  datos modificados entre lectura y bloqueo.
- **Asiento trazable.** `post_payroll_run_accounting` debita la cuenta `expense`
  por el devengado y acredita `payable` por el neto y, si hay, la cuenta de
  deducciones. Usa `ASI-NOM-YYYY-XXXX`, `reference_document = PayrollRun.code`,
  `entry_date = period_end` y es idempotente por ese código.
- **Rollback atómico.** Con `commit=False`, `hr._atomic` confirma asiento y
  estado juntos; si falla la contabilización (PUC incompleto, periodo cerrado o
  partida descuadrada), `ROLLBACK` y `PayrollAccountingError` (400) dejan el
  periodo en `DRAFT` sin asiento, permitiendo reintentar.
- **Inmutabilidad.** Reaprobar o intentar recalcular/cambiar el estado en
  `APPROVED`/`PAID` responde 409; la corrección es un nuevo periodo con
  `is_adjustment = True`.
- **Coherencia de caché.** Generar y aprobar invalidan `hrKeys.payrolls` y el
  detalle del periodo, de modo que la interfaz refleja el nuevo estado y los
  desprendibles sin recargar la página.
