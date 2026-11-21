# Diagramas técnicos — Módulo `accounting`

Documentación visual del módulo de Finanzas y Contabilidad, derivada de
`specs/accounting_spec.md`, del apéndice `APEND_PROJECT_MANIFIEST.md` (hito 10) y
del código final de `backend/src/modules/accounting/` y
`frontend/src/modules/accounting/`.

| Diagrama | Qué responde |
| --- | --- |
| Clases | Qué entidades SQLAlchemy existen, sus enums, relaciones y servicios de dominio |
| Componentes | Cómo viaja una petición desde React y TanStack Query hasta PostgreSQL y los módulos operativos |
| Secuencia | Qué ocurre al contabilizar un asiento o al registrar un cobro o pago |

> **Convención de nombres.** La spec y el apéndice usan `EntryStatus`,
> `DocumentType` y `PortfolioStatus`. En el código se materializan como
> `JournalEntryStatus`, `reference_document` con prefijos automáticos y
> `AccountBalanceStatus`, respectivamente. El diagrama conserva los nombres
> solicitados y esta sección los mapea al contrato real.

---

## 1. Diagrama de clases

Entidades SQLAlchemy de `models.py`, enums de estado/tipo, cardinalidades y los
métodos clave de `service.py`. `Decimal` significa `Numeric(14, 2)` en
PostgreSQL y viaja como cadena en la API.

```mermaid
classDiagram
    class Base {
        <<abstract>>
        +metadata
    }

    class AccountType {
        <<enumeration>>
        ASSET
        LIABILITY
        EQUITY
        REVENUE
        EXPENSE
    }

    class EntryStatus {
        <<enumeration>>
        DRAFT
        POSTED
        VOID
    }

    class DocumentType {
        <<enumeration>>
        INVOICE
        PURCHASE_ORDER
        CREDIT_NOTE
    }

    class PortfolioStatus {
        <<enumeration>>
        PENDING
        PARTIALLY_PAID
        PAID
        OVERDUE
    }

    class Account {
        +int id PK
        +str code UK
        +str name
        +AccountType account_type
        +int parent_id FK nullable
        +bool is_active
        +datetime created_at
        +list~Account~ children
        +list~JournalItem~ journal_items
    }

    class JournalEntry {
        +int id PK
        +str code UK
        +date entry_date
        +str description
        +str reference_document nullable
        +EntryStatus status
        +str created_by nullable
        +datetime posted_at nullable
        +datetime created_at
        +list~JournalItem~ items
        +list~AccountReceivable~ receivables
        +list~AccountPayable~ payables
        +list~PaymentRecord~ payments
    }

    class JournalItem {
        +int id PK
        +int journal_entry_id FK
        +int account_id FK
        +Decimal debit
        +Decimal credit
        +str description nullable
    }

    class AccountReceivable {
        +int id PK
        +int customer_id FK
        +int invoice_id FK nullable
        +int journal_entry_id FK nullable
        +Decimal total_amount
        +Decimal paid_amount
        +date due_date
        +PortfolioStatus status
        +datetime created_at
        +list~PaymentRecord~ payments
    }

    class AccountPayable {
        +int id PK
        +int supplier_id FK
        +str bill_reference
        +int journal_entry_id FK nullable
        +Decimal total_amount
        +Decimal paid_amount
        +date due_date
        +PortfolioStatus status
        +datetime created_at
        +list~PaymentRecord~ payments
    }

    class PaymentRecord {
        +int id PK
        +int receivable_id FK nullable
        +int payable_id FK nullable
        +int journal_entry_id FK nullable
        +Decimal amount
        +date payment_date
        +str reference nullable
        +datetime created_at
    }

    class AccountingPeriod {
        +int id PK
        +str name UK
        +date start_date
        +date end_date
        +bool is_closed
    }

    class AccountingService {
        <<service>>
        +create_account(db, data) Account
        +list_accounts(db, filters) list
        +update_account(db, account_id, data) Account
        +deactivate_account(db, account_id) Account
        +delete_account(db, account_id) None
        +create_journal_entry(db, data) JournalEntry
        +get_journal_entry(db, entry_id) JournalEntry
        +list_journal_entries(db, filters) list
        +ensure_account_active(db, account_id) Account
        +_ensure_balanced(entry) tuple
        +_ensure_open_period(db, entry_date) None
        +post_journal_entry(db, entry_id) JournalEntry
        +void_journal_entry(db, entry_id) JournalEntry
        +reverse_journal_entry(db, entry_id) JournalEntry
        +reject_journal_entry_mutation(db, entry_id) None
        +build_journal_entry_post_response(entry) Response
        +post_sales_invoice_accounting(db, document) AccountingResult
        +post_sales_credit_note_accounting(db, note) AccountingResult
        +post_purchase_receipt_accounting(db, receipt) AccountingResult
        +post_supplier_bill_accounting(db, bill) AccountingResult
        +list_account_receivables(db, filters) list
        +list_account_payables(db, filters) list
        +register_receivable_payment(db, target, amount) PaymentResult
        +register_payable_payment(db, target, amount) PaymentResult
        +list_payment_records(db, filters) list
        +get_trial_balance(db, window) TrialBalanceResponse
        +get_balance_sheet(db, window) BalanceSheetResponse
        +get_income_statement(db, window) IncomeStatementResponse
        +_unit_of_work(db, commit) Iterator
    }

    Base <|-- Account
    Base <|-- JournalEntry
    Base <|-- JournalItem
    Base <|-- AccountReceivable
    Base <|-- AccountPayable
    Base <|-- PaymentRecord
    Base <|-- AccountingPeriod

    Account "1" --> "0..*" Account : children
    JournalEntry "1" *-- "1..*" JournalItem : items
    Account "1" --> "0..*" JournalItem : journal_items
    JournalEntry "1" --> "0..*" AccountReceivable : receivables
    JournalEntry "1" --> "0..*" AccountPayable : payables
    JournalEntry "1" --> "0..*" PaymentRecord : payments
    AccountReceivable "1" --> "0..*" PaymentRecord : payments
    AccountPayable "1" --> "0..*" PaymentRecord : payments

    Account ..> AccountType : account_type
    JournalEntry ..> EntryStatus : status
    JournalEntry ..> DocumentType : reference_document
    AccountReceivable ..> PortfolioStatus : status
    AccountPayable ..> PortfolioStatus : status

    AccountingService ..> Account : valida is_active
    AccountingService ..> JournalEntry : publica y revierte
    AccountingService ..> JournalItem : exige partida doble
    AccountingService ..> AccountingPeriod : exige is_closed false
    AccountingService ..> AccountReceivable : actualiza saldo
    AccountingService ..> AccountPayable : actualiza saldo
    AccountingService ..> PaymentRecord : registra abono
    AccountingService ..> EntryStatus : POSTED y VOID
    AccountingService ..> PortfolioStatus : PENDING a PAID
```

### Reglas reflejadas en el modelo

- `Account.parent_id` es autorreferencial con `ON DELETE RESTRICT`: una cuenta
  con subcuentas o movimientos no se elimina, solo se desactiva con
  `is_active = False`.
- `JournalEntry.items` usa `CASCADE`; las líneas dependen del comprobante. El
  resto de las claves foráneas financieras usan `RESTRICT` para conservar
  historial.
- `JournalItem` garantiza en base de datos `debit >= 0`, `credit >= 0` y
  `NOT (debit > 0 AND credit > 0)`. El equilibrio exacto y el mínimo de dos
  líneas se validan en `post_journal_entry`.
- `POSTED` es inmutable: `void_journal_entry` solo pasa `DRAFT` a `VOID`; un
  asiento publicado se corrige con `reverse_journal_entry`, que crea un
  comprobante `REV-YYYY-XXXX` nuevo con débitos y créditos invertidos.
- `PortfolioStatus` es el mismo enum para CxC y CxP. `OVERDUE` se fija en la
  cartera y se conserva en abonos parciales mientras quede saldo.
- `DocumentType` es el tipo conceptual de la spec (`INVOICE`,
  `PURCHASE_ORDER`, `CREDIT_NOTE`). No existe como enum nativo: la procedencia
  se guarda en `reference_document` y se distingue con los prefijos
  `ASI-FAC`, `ASI-NC`, `ASI-REC`, `ASI-FCP`, `ASI-COB` y `ASI-PAG`.
- `AccountingPeriod` no tiene FK: `post_journal_entry` y los pagos comprueban
  por rango de fechas que no exista un periodo con `is_closed = True`.
- Los reportes solo leen asientos `POSTED` mediante `_posted_account_totals`;
  `DRAFT` y `VOID` no afectan saldos ni estados financieros.

---

## 2. Diagrama de componentes

Arquitectura full-stack: vistas React → guardias RBAC → hooks de TanStack Query
y cliente HTTP → routers, esquemas y servicios de FastAPI → tablas PostgreSQL,
con la automatización contable de los módulos operativos.

```mermaid
flowchart TB
    subgraph CLIENTE["Frontend React 19 + Vite"]
        direction TB
        USR["Usuario con rol accounting o administrator"]
        ROUTES["routes/index.tsx<br/>accounting redirige a accounts<br/>accounts journal receivables reports"]
        GUARD["routes/guards.tsx<br/>RequireModule module accounting<br/>RequireRole accounting administrator"]
        PUC["ChartOfAccountsPage<br/>alta edición desactivación"]
        JOURNAL["JournalEntriesPage<br/>borradores post void reverse"]
        PORTFOLIO["ReceivablesPayablesPage<br/>CxC CxP pagos historial"]
        REPORTS["FinancialReportsPage<br/>trial balance balance sheet income"]
        FORMS["AccountForm JournalEntryForm PaymentForm<br/>AccountingDialog AccountingTabs<br/>AccountingStatusBadge"]
        UTILS["constants format errors<br/>canWriteModule"]
    end

    subgraph DATA["Capa de datos del cliente"]
        direction TB
        HOOKS["hooks.ts<br/>useAccounts useJournalEntries<br/>useReceivables usePayables usePayments<br/>useTrialBalance useBalanceSheet useIncomeStatement<br/>mutaciones con invalidación"]
        KEYS["api.ts accountingKeys<br/>accounts journalEntries receivables<br/>payables payments reports"]
        HTTP["api.ts + api/client.ts<br/>apiRequest buildQuery<br/>ApiError 400 404 409 422"]
    end

    subgraph API["API FastAPI /api/v1/accounting"]
        direction TB
        RBAC["require_accounting<br/>require_roles ACCOUNTING<br/>ADMINISTRATOR bypass"]
        ROUTERS["router.py<br/>accounts journal-entries receivables<br/>payables payments reports"]
        SCHEMAS["schemas.py Pydantic v2<br/>AccountCreate JournalEntryCreate<br/>PaymentCreate PaymentRecordRequest<br/>ReportResponse"]
        SERVICES["service.py<br/>partida doble post void reverse<br/>automatización pagos reportes<br/>_unit_of_work ACID"]
        MODELS["models.py SQLAlchemy 2.x<br/>Mapped mapped_column CHECK FK"]
        ERR["accounting_exception_handler<br/>AccountingServiceError a HTTP"]
    end

    subgraph OPS["Módulos operativos"]
        direction TB
        SALES["sales<br/>facturas notas crédito<br/>post_sales_invoice_accounting"]
        PURCHASING["purchasing<br/>recepciones facturas proveedor<br/>post_purchase_receipt_accounting"]
        HR["hr<br/>nómina como EXPENSE<br/>integración planificada"]
    end

    subgraph DB["PostgreSQL · esquema accounting"]
        direction TB
        T_ACC["accounts"]
        T_JE["journal_entries"]
        T_JI["journal_items"]
        T_AR["account_receivables"]
        T_AP["account_payables"]
        T_PR["payment_records"]
        T_PER["accounting_periods"]
        T_ENUM["enum account_type journal_entry_status<br/>account_balance_status"]
        T_OPS["tablas operativas<br/>customers invoices suppliers<br/>goods_receipts supplier_bills"]
    end

    USR --> ROUTES
    ROUTES --> GUARD
    GUARD --> PUC
    GUARD --> JOURNAL
    GUARD --> PORTFOLIO
    GUARD --> REPORTS
    PUC --> FORMS
    JOURNAL --> FORMS
    PORTFOLIO --> FORMS
    PUC --> UTILS
    JOURNAL --> UTILS
    PORTFOLIO --> UTILS
    REPORTS --> UTILS

    PUC -->|"useAccounts y mutaciones"| HOOKS
    JOURNAL -->|"useJournalEntries post void reverse"| HOOKS
    PORTFOLIO -->|"useReceivables usePayables usePayments"| HOOKS
    REPORTS -->|"useTrialBalance useBalanceSheet useIncomeStatement"| HOOKS
    HOOKS --> KEYS
    HOOKS --> HTTP

    HTTP -->|"GET POST PATCH DELETE bajo api v1"| ROUTERS
    ROUTERS --> RBAC
    ROUTERS -->|"payload JSON snake_case"| SCHEMAS
    SCHEMAS -->|"datos validados"| SERVICES
    SERVICES --> MODELS
    ROUTERS -->|"errores de dominio"| ERR
    ERR -->|"detail 400 404 409"| HTTP
    HTTP -->|"JSON tipado Decimal como string"| HOOKS
    HOOKS -->|"invalida ledger y reports"| VIEWS_INV["Vistas y pestañas activas"]

    SALES -->|"asiento automático commit opcional"| SERVICES
    PURCHASING -->|"asiento automático commit opcional"| SERVICES
    HR -.->|"sin integración en el código actual"| SERVICES
    SALES --> T_OPS
    PURCHASING --> T_OPS

    MODELS --> T_ACC
    MODELS --> T_JE
    MODELS --> T_JI
    MODELS --> T_AR
    MODELS --> T_AP
    MODELS --> T_PR
    MODELS --> T_PER
    MODELS --> T_ENUM
```

### Lectura del diagrama

- **Doble guardia RBAC.** `RequireModule` valida `allowed_modules` y
  `RequireRole` exige `accounting` o `administrator`, reflejando
  `require_roles([RoleEnum.ACCOUNTING])` con bypass de administrador en el
  backend.
- **Una sola capa de datos.** Las vistas no llaman a `fetch`: consumen
  `hooks.ts`, que delega en `api.ts` y comparte `accountingKeys` para invalidar
  diario, cartera, pagos y reportes tras cada mutación.
- **Solo la pestaña activa consulta.** `ReceivablesPayablesPage` y
  `FinancialReportsPage` pasan `enabled` a los hooks para no lanzar peticiones
  innecesarias.
- **Integración real y planificada.** `sales` y `purchasing` llaman a los
  servicios automáticos con `commit=False` opcional; `hr` aparece con trazo
  discontinuo porque el módulo aún no existe en el código actual y solo está
  previsto como futuro origen de asientos de nómina.
- **ACID en el servicio.** `_unit_of_work` y `_atomic` agrupan asiento,
  `PaymentRecord` y saldo de cartera en un único `COMMIT`, con `ROLLBACK`
  automático ante cualquier excepción de dominio.

---

## 3. Diagrama de secuencia — contabilización y registro de cobros o pagos

Flujo completo para `POST /journal-entries/{id}/post` (en la spec
`/entries/{id}/post`) y `POST /payments`. Incluye partida doble, cuentas activas,
periodo abierto, transacción ACID, transición de cartera e inmutabilidad.

```mermaid
sequenceDiagram
    autonumber
    actor Op as Usuario
    participant UI as Vistas React
    participant Q as TanStack Query
    participant R as Router y Pydantic
    participant S as accounting.services
    participant DB as PostgreSQL

    Op->>UI: Contabilizar asiento en JournalEntriesPage
    UI->>Q: usePostJournalEntry entryId
    Q->>R: POST journal-entries / id / post
    R->>R: require_accounting require_roles ACCOUNTING con bypass ADMINISTRATOR
    R->>S: post_journal_entry db entry_id

    S->>DB: SELECT journal_entries con FOR UPDATE
    alt Estado POSTED o VOID
        S--xR: ImmutableJournalEntryError o InvalidJournalEntryStateError
        R--xQ: 400 o 409 con detail
        Q--xUI: errorHint
        UI--xOp: Aviso de asiento inmutable
    else Estado DRAFT
        S->>DB: SELECT accounts por id de las líneas
        alt Alguna cuenta con is_active False
            S->>DB: ROLLBACK sin cambios
            S--xR: 400 InactiveAccountError
            R--xQ: ApiError 400
            Q--xUI: errorHint de cuenta inactiva
            UI--xOp: Aviso de reactivar la cuenta
        else Todas las cuentas activas
            S->>DB: SELECT accounting_periods por rango de entry_date
            alt Periodo con is_closed True
                S->>DB: ROLLBACK sin cambios
                S--xR: 400 ClosedAccountingPeriodError
                R--xQ: ApiError 400
                Q--xUI: errorHint de periodo cerrado
                UI--xOp: Aviso de periodo no editable
            else Periodo abierto is_closed False
                S->>S: _ensure_balanced suma debitos igual suma creditos
                alt Asiento desequilibrado o sin dos líneas
                    S->>DB: ROLLBACK sin cambios
                    S--xR: 400 UnbalancedJournalEntryError
                    R--xQ: ApiError 400
                    Q--xUI: errorHint de partida doble
                    UI--xOp: Aviso de diferencia debito credito
                else Partida doble correcta
                    Note over S,DB: ACID una sola transaccion para estado y posted_at
                    S->>DB: UPDATE journal_entries status POSTED posted_at now
                    S->>DB: COMMIT
                    S-->>R: JournalEntryPostResponse con totales
                    R-->>Q: 200 JSON
                    Q->>Q: invalida diario cartera pagos y reportes
                    Q-->>UI: Asiento publicado
                    UI-->>Op: Badge POSTED y acciones void reverse
                end
            end
        end
    end

    Op->>UI: Registrar cobro o pago en ReceivablesPayablesPage
    UI->>Q: useRegisterPayment o useRegisterReceivablePayment
    Q->>R: POST payments o POST receivables / id / payments
    R->>R: require_accounting y PaymentCreate con un solo destino
    R->>S: register_receivable_payment db payload
    S->>DB: SELECT account_receivables con FOR UPDATE

    alt Importe invalido o superior al saldo
        S--xR: 400 InvalidSourceDocumentError
        R--xQ: ApiError 400
        Q--xUI: errorHint de saldo
        UI--xOp: Aviso sin mutar paid_amount
    else Importe mayor que cero y dentro del saldo
        S->>DB: SELECT accounts activas de caja y CxC
        S->>DB: SELECT accounting_periods con is_closed False
        S->>S: _build_posted_entry y _ensure_balanced
        Note over S,DB: ACID asiento PaymentRecord y saldo en un COMMIT
        S->>DB: INSERT journal_entries POSTED prefijo ASI-COB
        S->>DB: INSERT journal_items debe Caja o Banco haber CxC
        S->>DB: INSERT payment_records con journal_entry_id
        S->>DB: UPDATE account_receivables paid_amount y status
        S->>S: PENDING pasa a PARTIALLY_PAID y luego PAID al liquidar
        S->>DB: COMMIT
        S-->>R: PaymentRecordResponse 201
        R-->>Q: 201 JSON
        Q->>Q: invalida ledger y reports
        Q-->>UI: Saldo e historial refrescados
        UI-->>Op: Badge PARTIALLY_PAID o PAID
    end

    Op->>UI: Intentar anular o editar un asiento publicado
    UI->>Q: useVoidJournalEntry
    Q->>R: POST journal-entries / id / void
    R->>S: void_journal_entry db entry_id
    S--xR: 400 ImmutableJournalEntryError
    R--xQ: ApiError 400
    Q--xUI: errorHint de reversión
    UI-->>Op: Aviso de usar POST journal-entries / id / reverse

    Note over UI,DB: POSTED no se modifica ni se borra VOID solo para DRAFT
```

### Puntos críticos del flujo

- **Orden de validación.** Estado del asiento, cuentas `is_active`,
  `is_closed = False` del periodo y equilibrio débito/crédito. Cualquier fallo
  ocurre antes del `COMMIT`, por lo que no quedan filas parciales.
- **Bloqueo optimista/pesimista.** `get_journal_entry(..., for_update=True)` y
  `SELECT ... FOR UPDATE` sobre la cartera serializan publicaciones y abonos.
- **Pago atómico.** El asiento `ASI-COB`/`ASI-PAG`, el `PaymentRecord` y el
  `paid_amount` se confirman juntos; si falla `_apply_payment_to_balance`, el
  `ROLLBACK` elimina los tres efectos.
- **Transición de cartera.** `PENDING → PARTIALLY_PAID` mientras quede saldo y
  `PAID` cuando `paid_amount = total_amount`; `OVERDUE` se conserva si ya estaba
  fijado y aún hay deuda.
- **Inmutabilidad.** No existen `PATCH`/`DELETE` HTTP para asientos; los
  listeners ORM `before_update`/`before_delete` son la segunda capa de defensa.
- **Coherencia de caché.** Publicar o pagar invalida simultáneamente diario,
  CxC, CxP, historial de pagos y los tres reportes, que solo leen `POSTED`.
