"""Suite BDD y de regresión consolidada del módulo ``accounting``.

Cubre los 13 escenarios de aceptación de ``specs/accounting_spec.md``
(sección 5) y las reglas críticas 1-9. Los flujos que el router publica por HTTP
se ejercitan con ``TestClient``; la automatización ``sales``/``purchasing``, el
cierre de periodos y la inmutabilidad de bajo nivel se validan en la capa de
servicios porque el router todavía no expone esos endpoints.

Se reutiliza el patrón de SQLite en memoria y override de ``get_db`` de las
pruebas HTTP ya existentes, de modo que cada prueba parte de un esquema limpio.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Generator
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault("DATABASE_URL", "sqlite://")

from src.core.database import Base, get_db  # noqa: E402
from src.core.security import create_access_token, hash_password  # noqa: E402
from src.main import app  # noqa: E402
from src.modules.accounting import service as accounting_service  # noqa: E402
from src.modules.accounting.models import (  # noqa: E402
    Account,
    AccountBalanceStatus,
    AccountPayable,
    AccountReceivable,
    AccountType,
    AccountingPeriod,
    JournalEntry,
    JournalEntryStatus,
    JournalItem,
    PaymentRecord,
)
from src.modules.accounting.schemas import (  # noqa: E402
    AccountCreate,
    JournalEntryCreate,
    JournalItemCreate,
)
from src.modules.inventory.models import Product, Warehouse  # noqa: E402
from src.modules.purchasing.models import (  # noqa: E402
    GoodsReceipt,
    GoodsReceiptItem,
    PurchaseOrder,
    PurchaseOrderItem,
    PurchaseOrderStatus,
    Supplier,
    SupplierBill,
    SupplierBillStatus,
)
from src.modules.sales.models import Customer, Invoice, InvoiceStatus  # noqa: E402
from src.modules.users.models import Role, RoleEnum, User  # noqa: E402

ACCOUNTING_URL = "/api/v1/accounting"
_HASHED_PASSWORD = hash_password("Accounting1234!")
_ISSUE_DATE = date(2026, 11, 15)
_NOV_FROM = date(2026, 11, 1)
_NOV_TO = date(2026, 11, 30)
_PAST_DUE = date.today() - timedelta(days=15)
_FUTURE_DUE = date.today() + timedelta(days=30)


# --------------------------------------------------------------------------- #
# Fixtures compartidas
# --------------------------------------------------------------------------- #


@pytest.fixture()
def db_engine() -> Generator[Engine, None, None]:
    """Engine SQLite aislado, sin el ``BEGIN`` implícito de pysqlite."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _disable_implicit_begin(
        dbapi_connection: Any, _connection_record: Any
    ) -> None:
        dbapi_connection.isolation_level = None

    @event.listens_for(engine, "begin")
    def _emit_begin(connection: Any) -> None:
        connection.exec_driver_sql("BEGIN")

    Base.metadata.create_all(engine)
    try:
        yield engine
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


@pytest.fixture()
def db_session(db_engine: Engine) -> Generator[Session, None, None]:
    factory = sessionmaker(bind=db_engine, expire_on_commit=False)
    with factory() as session:
        yield session


@pytest.fixture()
def client(db_session: Session) -> Generator[TestClient, None, None]:
    """Cliente HTTP con la sesión de prueba inyectada en ``get_db``."""

    def override_get_db() -> Generator[Session, None, None]:
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.pop(get_db, None)


def _role(db_session: Session, name: RoleEnum, modules: list[str]) -> Role:
    role = db_session.scalar(select(Role).where(Role.name == name))
    if role is None:
        role = Role(name=name, description=name.value, allowed_modules=modules)
        db_session.add(role)
        db_session.flush()
    return role


def _user(
    db_session: Session, *, role: Role, username: str, email: str
) -> User:
    user = User(
        email=email,
        username=username,
        full_name=username.title(),
        hashed_password=_HASHED_PASSWORD,
        role_id=role.id,
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture()
def accounts(db_session: Session) -> dict[str, User]:
    admin_role = _role(db_session, RoleEnum.ADMINISTRATOR, ["*"])
    accounting_role = _role(
        db_session,
        RoleEnum.ACCOUNTING,
        ["accounting", "sales:read", "purchasing:read"],
    )
    sales_role = _role(db_session, RoleEnum.SALES, ["sales", "inventory:read"])
    db_session.commit()

    return {
        "admin": _user(
            db_session,
            role=admin_role,
            username="admin_bdd",
            email="admin-bdd@example.com",
        ),
        "accounting": _user(
            db_session,
            role=accounting_role,
            username="contador_bdd",
            email="contador-bdd@example.com",
        ),
        "sales": _user(
            db_session,
            role=sales_role,
            username="vendedor_bdd",
            email="vendedor-bdd@example.com",
        ),
    }


def _headers(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id)}"}


@pytest.fixture()
def admin_headers(accounts: dict[str, User]) -> dict[str, str]:
    return _headers(accounts["admin"])


@pytest.fixture()
def accounting_headers(accounts: dict[str, User]) -> dict[str, str]:
    return _headers(accounts["accounting"])


@pytest.fixture()
def sales_headers(accounts: dict[str, User]) -> dict[str, str]:
    return _headers(accounts["sales"])


@pytest.fixture()
def chart(db_session: Session) -> dict[str, Account]:
    """PUC con todos los códigos por defecto de la automatización."""
    definitions = {
        "cash": ("110505", "Caja General", AccountType.ASSET),
        "receivable": ("130505", "Clientes", AccountType.ASSET),
        "inventory": ("1435", "Inventario", AccountType.ASSET),
        "input_tax": ("135515", "IVA descontable", AccountType.ASSET),
        "output_tax": ("240805", "IVA por pagar", AccountType.LIABILITY),
        "payable": ("220505", "Proveedores", AccountType.LIABILITY),
        "equity": ("3105", "Capital social", AccountType.EQUITY),
        "revenue": ("4135", "Ventas", AccountType.REVENUE),
        "expense": ("5100", "Gastos", AccountType.EXPENSE),
    }
    return {
        role: accounting_service.create_account(
            db_session,
            AccountCreate(code=code, name=name, account_type=kind),
        )
        for role, (code, name, kind) in definitions.items()
    }


@pytest.fixture()
def customer(db_session: Session) -> Customer:
    entity = Customer(
        tax_id="900111222-1",
        company_name="Cliente BDD",
        contact_name="Ana Pérez",
        email="ana@example.com",
        address="Calle 1 # 2-3",
        credit_limit=Decimal("10000.00"),
        is_active=True,
    )
    db_session.add(entity)
    db_session.commit()
    db_session.refresh(entity)
    return entity


@pytest.fixture()
def supplier(db_session: Session) -> Supplier:
    entity = Supplier(
        tax_id="800999888-1",
        company_name="Proveedor BDD",
        contact_name="Luis Gómez",
        email="proveedor@example.com",
        address="Carrera 4 # 5-6",
        payment_terms_days=30,
        is_active=True,
    )
    db_session.add(entity)
    db_session.commit()
    db_session.refresh(entity)
    return entity


@pytest.fixture()
def invoice(db_session: Session, customer: Customer) -> Invoice:
    entity = Invoice(
        code="FAC-BDD-0001",
        sales_order_id=None,
        customer_id=customer.id,
        status=InvoiceStatus.ISSUED,
        issue_date=_ISSUE_DATE,
        due_date=_FUTURE_DUE,
        total=Decimal("1200.00"),
        balance_due=Decimal("1200.00"),
    )
    db_session.add(entity)
    db_session.commit()
    db_session.refresh(entity)
    return entity


@pytest.fixture()
def purchase_document(
    db_session: Session, supplier: Supplier
) -> tuple[GoodsReceipt, SupplierBill]:
    """Recepción de 800 y factura de 900 con origen en una OC aprobada."""
    warehouse = Warehouse(
        code="WH-BDD-01", name="Bodega BDD", address=None, is_active=True
    )
    product = Product(
        sku="SKU-BDD-01",
        name="Producto BDD",
        description=None,
        unit_price=Decimal("100.00"),
        minimum_stock=0,
        is_active=True,
    )
    db_session.add_all([warehouse, product])
    db_session.flush()

    order = PurchaseOrder(
        code="OC-BDD-0001",
        supplier_id=supplier.id,
        status=PurchaseOrderStatus.APPROVED,
        issue_date=_ISSUE_DATE,
        expected_delivery_date=_FUTURE_DUE,
        subtotal=Decimal("800.00"),
        tax_amount=Decimal("0.00"),
        total=Decimal("800.00"),
    )
    db_session.add(order)
    db_session.flush()

    order_item = PurchaseOrderItem(
        purchase_order_id=order.id,
        product_id=product.id,
        quantity=10,
        received_quantity=10,
        unit_price=Decimal("80.00"),
        tax_rate=Decimal("0.00"),
        subtotal=Decimal("800.00"),
    )
    db_session.add(order_item)
    db_session.flush()

    receipt = GoodsReceipt(
        code="REC-BDD-0001",
        purchase_order_id=order.id,
        warehouse_id=warehouse.id,
        receipt_date=_ISSUE_DATE,
        received_by="contador_bdd",
        notes=None,
    )
    receipt.items.append(
        GoodsReceiptItem(purchase_order_item_id=order_item.id, quantity=10)
    )
    db_session.add(receipt)
    db_session.flush()

    bill = SupplierBill(
        code="FCP-BDD-0001",
        supplier_id=supplier.id,
        purchase_order_id=order.id,
        goods_receipt_id=receipt.id,
        supplier_invoice_number="PROV-BDD-001",
        status=SupplierBillStatus.PENDING,
        issue_date=_ISSUE_DATE,
        due_date=_FUTURE_DUE,
        subtotal=Decimal("900.00"),
        tax_amount=Decimal("0.00"),
        total=Decimal("900.00"),
        balance_due=Decimal("900.00"),
    )
    db_session.add(bill)
    db_session.commit()
    db_session.refresh(receipt)
    db_session.refresh(bill)
    return receipt, bill


@pytest.fixture()
def automated_balances(
    db_session: Session,
    chart: dict[str, Account],
    invoice: Invoice,
    purchase_document: tuple[GoodsReceipt, SupplierBill],
) -> dict[str, AccountReceivable | AccountPayable]:
    """CxC y CxP generadas por la automatización, listas para abonar."""
    _, bill = purchase_document
    receivable = accounting_service.post_sales_invoice_accounting(
        db_session, invoice.id
    ).balance
    payable = accounting_service.post_supplier_bill_accounting(db_session, bill.id).balance
    assert isinstance(receivable, AccountReceivable)
    assert isinstance(payable, AccountPayable)
    return {"receivable": receivable, "payable": payable}


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _entry_payload(
    code: str,
    debit_id: int,
    credit_id: int,
    debit: str,
    credit: str,
    *,
    entry_date: date = _ISSUE_DATE,
    description: str = "Asiento de la suite BDD",
) -> dict[str, Any]:
    return {
        "code": code,
        "entry_date": entry_date.isoformat(),
        "description": description,
        "items": [
            {"account_id": debit_id, "debit": debit},
            {"account_id": credit_id, "credit": credit},
        ],
    }


def _create_entry(
    client: TestClient,
    headers: dict[str, str],
    code: str,
    chart: dict[str, Account],
    debit: str = "500.00",
    credit: str = "500.00",
    *,
    debit_role: str = "cash",
    credit_role: str = "revenue",
    entry_date: date = _ISSUE_DATE,
) -> dict[str, Any]:
    payload = _entry_payload(
        code,
        chart[debit_role].id,
        chart[credit_role].id,
        debit,
        credit,
        entry_date=entry_date,
    )
    response = client.post(
        f"{ACCOUNTING_URL}/journal-entries", headers=headers, json=payload
    )
    assert response.status_code == 201, response.text
    return response.json()


def _post_entry(
    client: TestClient, headers: dict[str, str], entry_id: int
) -> Any:
    return client.post(
        f"{ACCOUNTING_URL}/journal-entries/{entry_id}/post", headers=headers
    )


def _pay(
    client: TestClient,
    headers: dict[str, str],
    amount: str,
    *,
    receivable_id: int | None = None,
    payable_id: int | None = None,
    reference: str = "REF-BDD",
) -> Any:
    payload: dict[str, Any] = {"amount": amount, "reference": reference}
    if receivable_id is not None:
        payload["receivable_id"] = receivable_id
    else:
        payload["payable_id"] = payable_id
    return client.post(f"{ACCOUNTING_URL}/payments", headers=headers, json=payload)


def _report(
    client: TestClient, headers: dict[str, str], name: str, **params: Any
) -> dict[str, Any]:
    response = client.get(
        f"{ACCOUNTING_URL}/reports/{name}", headers=headers, params=params
    )
    assert response.status_code == 200, response.text
    return response.json()


def _lines(entry: JournalEntry) -> list[tuple[str, Decimal, Decimal]]:
    return [(item.account.code, item.debit, item.credit) for item in entry.items]


def _count(db: Session, model: Any) -> int:
    return int(db.scalar(select(func.count()).select_from(model)) or 0)


def _posted_sale(
    db_session: Session,
    chart: dict[str, Account],
    code: str,
    amount: str,
    *,
    entry_date: date = _ISSUE_DATE,
) -> JournalEntry:
    draft = accounting_service.create_journal_entry(
        db_session,
        _service_payload(chart, code, amount, entry_date=entry_date),
    )
    return accounting_service.post_journal_entry(db_session, draft.id)


def _service_payload(
    chart: dict[str, Account],
    code: str,
    amount: str,
    *,
    entry_date: date = _ISSUE_DATE,
    description: str = "Venta al contado BDD",
) -> JournalEntryCreate:
    return JournalEntryCreate(
        code=code,
        entry_date=entry_date,
        description=description,
        created_by="suite_bdd",
        items=[
            JournalItemCreate(account_id=chart["cash"].id, debit=Decimal(amount)),
            JournalItemCreate(account_id=chart["revenue"].id, credit=Decimal(amount)),
        ],
    )


# --------------------------------------------------------------------------- #
# Escenario 1 — contabilización exitosa por partida doble
# --------------------------------------------------------------------------- #


def test_scenario_01_balanced_entry_is_posted_and_updates_balances(
    client: TestClient,
    accounting_headers: dict[str, str],
    chart: dict[str, Account],
    db_session: Session,
) -> None:
    draft = _create_entry(client, accounting_headers, "ASI-BDD-0001", chart)
    assert draft["status"] == JournalEntryStatus.DRAFT.value
    assert draft["posted_at"] is None
    assert len(draft["items"]) == 2

    response = _post_entry(client, accounting_headers, draft["id"])
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == JournalEntryStatus.POSTED.value
    assert body["posted_at"] is not None
    assert body["total_debit"] == "500.00"
    assert body["total_credit"] == "500.00"

    entry = db_session.get(JournalEntry, draft["id"])
    assert entry is not None
    assert entry.status is JournalEntryStatus.POSTED

    trial = _report(
        client,
        accounting_headers,
        "trial-balance",
        date_from=_NOV_FROM,
        date_to=_NOV_TO,
    )
    assert trial["total_debit"] == "500.00"
    assert trial["total_credit"] == "500.00"

    balance = _report(
        client,
        accounting_headers,
        "balance-sheet",
        date_from=_NOV_FROM,
        date_to=_NOV_TO,
    )
    assert balance["total_assets"] == "500.00"
    assert balance["total_liabilities"] == "0.00"
    assert balance["difference"] == "500.00"

    income = _report(
        client,
        accounting_headers,
        "income-statement",
        date_from=_NOV_FROM,
        date_to=_NOV_TO,
    )
    assert income["total_revenue"] == "500.00"
    assert income["net_income"] == "500.00"


# --------------------------------------------------------------------------- #
# Escenario 2 — rechazo por desequilibrio
# --------------------------------------------------------------------------- #


def test_scenario_02_unbalanced_entry_is_rejected_with_http_400(
    client: TestClient,
    accounting_headers: dict[str, str],
    chart: dict[str, Account],
) -> None:
    draft = _create_entry(
        client, accounting_headers, "ASI-BDD-0002", chart, "500.00", "450.00"
    )

    response = _post_entry(client, accounting_headers, draft["id"])
    assert response.status_code == 400
    assert "equilibrado" in response.json()["detail"]

    detail = client.get(
        f"{ACCOUNTING_URL}/journal-entries/{draft['id']}", headers=accounting_headers
    )
    assert detail.json()["status"] == JournalEntryStatus.DRAFT.value
    assert detail.json()["posted_at"] is None

    trial = _report(
        client,
        accounting_headers,
        "trial-balance",
        date_from=_NOV_FROM,
        date_to=_NOV_TO,
    )
    assert trial["total_debit"] == "0.00"
    assert trial["total_credit"] == "0.00"


# --------------------------------------------------------------------------- #
# Escenario 3 — inmutabilidad del asiento publicado
# --------------------------------------------------------------------------- #


def test_scenario_03_posted_entry_cannot_be_modified_or_deleted(
    client: TestClient,
    accounting_headers: dict[str, str],
    chart: dict[str, Account],
    db_session: Session,
) -> None:
    draft = _create_entry(client, accounting_headers, "ASI-BDD-0003", chart)
    assert _post_entry(client, accounting_headers, draft["id"]).status_code == 200

    replacement = _service_payload(chart, draft["code"], "600.00")
    with pytest.raises(accounting_service.ImmutableJournalEntryError) as exc:
        accounting_service.update_journal_entry(db_session, draft["id"], replacement)
    assert exc.value.status_code == 400

    with pytest.raises(accounting_service.ImmutableJournalEntryError):
        accounting_service.delete_journal_entry(db_session, draft["id"])
    with pytest.raises(accounting_service.ImmutableJournalEntryError):
        accounting_service.reject_journal_entry_mutation(db_session, draft["id"])

    # Defensa en profundidad: el listener ORM también bloquea el cambio directo.
    entry = db_session.get(JournalEntry, draft["id"])
    assert entry is not None
    entry.description = "Intento directo de modificación"
    with pytest.raises(accounting_service.ImmutableJournalEntryError):
        db_session.commit()
    db_session.rollback()

    db_session.delete(entry)
    with pytest.raises(accounting_service.ImmutableJournalEntryError):
        db_session.commit()
    db_session.rollback()
    assert (
        db_session.get(JournalEntry, draft["id"]).status
        is JournalEntryStatus.POSTED
    )

    # Las transiciones HTTP tampoco permiten editar, anular o volver a publicar.
    assert _post_entry(client, accounting_headers, draft["id"]).status_code == 400
    void_response = client.post(
        f"{ACCOUNTING_URL}/journal-entries/{draft['id']}/void",
        headers=accounting_headers,
    )
    assert void_response.status_code == 400

    reversal = client.post(
        f"{ACCOUNTING_URL}/journal-entries/{draft['id']}/reverse",
        headers=accounting_headers,
    )
    assert reversal.status_code == 201, reversal.text
    assert reversal.json()["status"] == JournalEntryStatus.POSTED.value
    assert reversal.json()["reference_document"] == draft["code"]
    assert reversal.json()["items"][0]["debit"] == "0.00"
    assert reversal.json()["items"][0]["credit"] == "500.00"


# --------------------------------------------------------------------------- #
# Escenario 4 — cuenta inactiva
# --------------------------------------------------------------------------- #


def test_scenario_04_inactive_account_rejects_movements(
    client: TestClient,
    accounting_headers: dict[str, str],
    chart: dict[str, Account],
) -> None:
    created = client.post(
        f"{ACCOUNTING_URL}/accounts",
        headers=accounting_headers,
        json={
            "code": "110599",
            "name": "Caja inactiva",
            "account_type": AccountType.ASSET.value,
        },
    )
    assert created.status_code == 201, created.text
    inactive_id = created.json()["id"]

    patched = client.patch(
        f"{ACCOUNTING_URL}/accounts/{inactive_id}",
        headers=accounting_headers,
        json={"is_active": False},
    )
    assert patched.status_code == 200
    assert patched.json()["is_active"] is False

    rejected = client.post(
        f"{ACCOUNTING_URL}/journal-entries",
        headers=accounting_headers,
        json=_entry_payload(
            "ASI-BDD-INACT",
            inactive_id,
            chart["revenue"].id,
            "100.00",
            "100.00",
        ),
    )
    assert rejected.status_code == 400
    assert "inactiva" in rejected.json()["detail"]

    # La cuenta también se puede desactivar después de crear el borrador:
    # la publicación vuelve a validar que esté activa.
    draft = _create_entry(client, accounting_headers, "ASI-BDD-0004", chart)
    client.patch(
        f"{ACCOUNTING_URL}/accounts/{chart['cash'].id}",
        headers=accounting_headers,
        json={"is_active": False},
    )
    response = _post_entry(client, accounting_headers, draft["id"])
    assert response.status_code == 400
    assert "inactiva" in response.json()["detail"]
    detail = client.get(
        f"{ACCOUNTING_URL}/journal-entries/{draft['id']}", headers=accounting_headers
    )
    assert detail.json()["status"] == JournalEntryStatus.DRAFT.value


# --------------------------------------------------------------------------- #
# Escenario 5 — automatización desde sales
# --------------------------------------------------------------------------- #


def test_scenario_05_sales_invoice_posts_entry_and_receivable(
    db_session: Session,
    chart: dict[str, Account],
    invoice: Invoice,
    client: TestClient,
    accounting_headers: dict[str, str],
) -> None:
    result = accounting_service.post_sales_invoice_accounting(db_session, invoice.id)

    assert result.journal_entry.status is JournalEntryStatus.POSTED
    assert result.journal_entry.reference_document == invoice.code
    assert _lines(result.journal_entry) == [
        ("130505", Decimal("1200.00"), Decimal("0.00")),
        ("4135", Decimal("0.00"), Decimal("1200.00")),
    ]

    receivable = result.balance
    assert isinstance(receivable, AccountReceivable)
    assert receivable.total_amount == Decimal("1200.00")
    assert receivable.paid_amount == Decimal("0.00")
    assert receivable.status is AccountBalanceStatus.PENDING
    assert receivable.journal_entry_id == result.journal_entry.id

    repeated = accounting_service.post_sales_invoice_accounting(db_session, invoice.id)
    assert repeated.journal_entry.id == result.journal_entry.id
    assert _count(db_session, JournalEntry) == 1
    assert _count(db_session, AccountReceivable) == 1

    listed = client.get(
        f"{ACCOUNTING_URL}/receivables",
        headers=accounting_headers,
        params={"status": AccountBalanceStatus.PENDING.value},
    )
    assert receivable.id in [item["id"] for item in listed.json()]


# --------------------------------------------------------------------------- #
# Escenario 6 — automatización desde purchasing
# --------------------------------------------------------------------------- #


def test_scenario_06_purchasing_documents_post_entries_and_payables(
    db_session: Session,
    chart: dict[str, Account],
    purchase_document: tuple[GoodsReceipt, SupplierBill],
) -> None:
    receipt, bill = purchase_document

    receipt_result = accounting_service.post_purchase_receipt_accounting(
        db_session, receipt.id
    )
    assert receipt_result.journal_entry.status is JournalEntryStatus.POSTED
    assert _lines(receipt_result.journal_entry) == [
        ("1435", Decimal("800.00"), Decimal("0.00")),
        ("220505", Decimal("0.00"), Decimal("800.00")),
    ]
    receipt_balance = receipt_result.balance
    assert isinstance(receipt_balance, AccountPayable)
    assert receipt_balance.bill_reference == receipt.code
    assert receipt_balance.total_amount == Decimal("800.00")
    assert receipt_balance.status is AccountBalanceStatus.PENDING

    bill_result = accounting_service.post_supplier_bill_accounting(db_session, bill.id)
    assert bill_result.journal_entry.status is JournalEntryStatus.POSTED
    assert _lines(bill_result.journal_entry) == [
        ("1435", Decimal("900.00"), Decimal("0.00")),
        ("220505", Decimal("0.00"), Decimal("900.00")),
    ]
    bill_balance = bill_result.balance
    assert isinstance(bill_balance, AccountPayable)
    assert bill_balance.total_amount == Decimal("900.00")
    assert bill_balance.status is AccountBalanceStatus.PENDING

    assert _count(db_session, AccountPayable) == 2
    assert _count(db_session, JournalEntry) == 2


# --------------------------------------------------------------------------- #
# Escenario 7 — código duplicado
# --------------------------------------------------------------------------- #


def test_scenario_07_duplicate_journal_code_is_rejected(
    client: TestClient,
    accounting_headers: dict[str, str],
    chart: dict[str, Account],
    db_session: Session,
) -> None:
    first = _create_entry(client, accounting_headers, "ASI-BDD-DUPLICADO", chart)
    duplicate = client.post(
        f"{ACCOUNTING_URL}/journal-entries",
        headers=accounting_headers,
        json=_entry_payload(
            first["code"], chart["cash"].id, chart["revenue"].id, "500.00", "500.00"
        ),
    )
    assert duplicate.status_code == 409
    assert "Ya existe" in duplicate.json()["detail"]
    assert _count(db_session, JournalEntry) == 1

    # La unicidad del código del PUC se protege con el mismo criterio.
    duplicate_account = client.post(
        f"{ACCOUNTING_URL}/accounts",
        headers=accounting_headers,
        json={
            "code": "110505",
            "name": "Caja duplicada",
            "account_type": AccountType.ASSET.value,
        },
    )
    assert duplicate_account.status_code == 409
    assert "código" in duplicate_account.json()["detail"]


# --------------------------------------------------------------------------- #
# Escenario 8 — abono parcial
# --------------------------------------------------------------------------- #


def test_scenario_08_partial_payments_update_ar_and_ap(
    client: TestClient,
    accounting_headers: dict[str, str],
    automated_balances: dict[str, AccountReceivable | AccountPayable],
) -> None:
    receivable = automated_balances["receivable"]
    assert isinstance(receivable, AccountReceivable)
    response = _pay(
        client,
        accounting_headers,
        "400.00",
        receivable_id=receivable.id,
        reference="COB-BDD-400",
    )
    assert response.status_code == 201, response.text
    record = response.json()
    assert record["receivable_id"] == receivable.id
    assert record["amount"] == "400.00"
    assert record["journal_entry_id"] is not None

    detail = client.get(
        f"{ACCOUNTING_URL}/receivables/{receivable.id}", headers=accounting_headers
    )
    assert detail.json()["paid_amount"] == "400.00"
    assert detail.json()["status"] == AccountBalanceStatus.PARTIALLY_PAID.value

    payable = automated_balances["payable"]
    assert isinstance(payable, AccountPayable)
    response = _pay(
        client,
        accounting_headers,
        "300.00",
        payable_id=payable.id,
        reference="PAG-BDD-300",
    )
    assert response.status_code == 201, response.text
    detail = client.get(
        f"{ACCOUNTING_URL}/payables/{payable.id}", headers=accounting_headers
    )
    assert detail.json()["paid_amount"] == "300.00"
    assert detail.json()["status"] == AccountBalanceStatus.PARTIALLY_PAID.value

    history = client.get(
        f"{ACCOUNTING_URL}/payments",
        headers=accounting_headers,
        params={"reference": "COB-BDD-400"},
    )
    assert history.status_code == 200
    assert len(history.json()) == 1


# --------------------------------------------------------------------------- #
# Escenario 9 — liquidación total
# --------------------------------------------------------------------------- #


def test_scenario_09_full_payments_mark_balances_paid(
    client: TestClient,
    accounting_headers: dict[str, str],
    automated_balances: dict[str, AccountReceivable | AccountPayable],
) -> None:
    receivable = automated_balances["receivable"]
    assert isinstance(receivable, AccountReceivable)
    assert _pay(
        client, accounting_headers, "400.00", receivable_id=receivable.id
    ).status_code == 201

    # Con 800 pendientes, un abono de 900 excede el saldo y se rechaza.
    overflow = _pay(
        client, accounting_headers, "900.00", receivable_id=receivable.id
    )
    assert overflow.status_code == 400
    assert "excede" in overflow.json()["detail"]

    final = _pay(
        client, accounting_headers, "800.00", receivable_id=receivable.id
    )
    assert final.status_code == 201, final.text
    detail = client.get(
        f"{ACCOUNTING_URL}/receivables/{receivable.id}", headers=accounting_headers
    )
    assert detail.json()["paid_amount"] == "1200.00"
    assert detail.json()["status"] == AccountBalanceStatus.PAID.value

    # Ya liquidada, cualquier abono adicional también se rechaza.
    extra = _pay(client, accounting_headers, "1.00", receivable_id=receivable.id)
    assert extra.status_code == 400

    payable = automated_balances["payable"]
    assert isinstance(payable, AccountPayable)
    assert _pay(
        client, accounting_headers, "300.00", payable_id=payable.id
    ).status_code == 201
    final = _pay(client, accounting_headers, "600.00", payable_id=payable.id)
    assert final.status_code == 201, final.text
    detail = client.get(
        f"{ACCOUNTING_URL}/payables/{payable.id}", headers=accounting_headers
    )
    assert detail.json()["paid_amount"] == "900.00"
    assert detail.json()["status"] == AccountBalanceStatus.PAID.value


# --------------------------------------------------------------------------- #
# Escenario 10 — cierre de periodo
# --------------------------------------------------------------------------- #


def test_scenario_10_close_accounting_period(db_session: Session) -> None:
    period = AccountingPeriod(
        name="2026-10",
        start_date=date(2026, 10, 1),
        end_date=date(2026, 10, 31),
        is_closed=False,
    )
    db_session.add(period)
    db_session.commit()
    db_session.refresh(period)
    assert period.is_closed is False

    # El router de periodos aún no está publicado; la acción de cierre se
    # persiste directamente en el modelo, igual que hará el futuro endpoint.
    period.is_closed = True
    db_session.commit()
    db_session.refresh(period)
    assert period.is_closed is True
    assert (
        db_session.scalar(
            select(AccountingPeriod).where(AccountingPeriod.name == "2026-10")
        ).is_closed
        is True
    )


# --------------------------------------------------------------------------- #
# Escenario 11 — rechazo en periodo cerrado
# --------------------------------------------------------------------------- #


def test_scenario_11_posting_in_closed_period_is_rejected(
    client: TestClient,
    accounting_headers: dict[str, str],
    chart: dict[str, Account],
    db_session: Session,
) -> None:
    db_session.add(
        AccountingPeriod(
            name="2026-10",
            start_date=date(2026, 10, 1),
            end_date=date(2026, 10, 31),
            is_closed=True,
        )
    )
    db_session.commit()

    draft = _create_entry(
        client,
        accounting_headers,
        "ASI-BDD-OCT",
        chart,
        entry_date=date(2026, 10, 15),
    )
    response = _post_entry(client, accounting_headers, draft["id"])
    assert response.status_code == 400
    assert "periodo contable está cerrado" in response.json()["detail"]
    detail = client.get(
        f"{ACCOUNTING_URL}/journal-entries/{draft['id']}", headers=accounting_headers
    )
    assert detail.json()["status"] == JournalEntryStatus.DRAFT.value


# --------------------------------------------------------------------------- #
# Escenario 12 — importe de pago inválido
# --------------------------------------------------------------------------- #


def test_scenario_12_invalid_payment_amount_is_rejected_without_mutation(
    db_session: Session,
    client: TestClient,
    accounting_headers: dict[str, str],
    automated_balances: dict[str, AccountReceivable | AccountPayable],
) -> None:
    receivable = automated_balances["receivable"]
    assert isinstance(receivable, AccountReceivable)
    assert _pay(
        client, accounting_headers, "400.00", receivable_id=receivable.id
    ).status_code == 201
    records_before = _count(db_session, PaymentRecord)

    for amount in ("0.00", "-1.00"):
        invalid = _pay(
            client, accounting_headers, amount, receivable_id=receivable.id
        )
        assert invalid.status_code in (400, 422)

    with pytest.raises(accounting_service.InvalidSourceDocumentError) as exc:
        accounting_service.register_receivable_payment(
            db_session, receivable.id, Decimal("0.00")
        )
    assert exc.value.status_code == 400

    excessive = _pay(
        client, accounting_headers, "900.00", receivable_id=receivable.id
    )
    assert excessive.status_code == 400
    assert "excede" in excessive.json()["detail"]

    detail = client.get(
        f"{ACCOUNTING_URL}/receivables/{receivable.id}", headers=accounting_headers
    )
    assert detail.json()["paid_amount"] == "400.00"
    assert detail.json()["status"] == AccountBalanceStatus.PARTIALLY_PAID.value
    assert _count(db_session, PaymentRecord) == records_before


# --------------------------------------------------------------------------- #
# Escenario 13 — cartera vencida (OVERDUE)
# --------------------------------------------------------------------------- #


def test_scenario_13_overdue_balance_is_filterable_and_preserved_until_paid(
    db_session: Session,
    client: TestClient,
    accounting_headers: dict[str, str],
    chart: dict[str, Account],
    customer: Customer,
    supplier: Supplier,
) -> None:
    receivable = AccountReceivable(
        customer_id=customer.id,
        total_amount=Decimal("1000.00"),
        paid_amount=Decimal("0.00"),
        due_date=_PAST_DUE,
        status=AccountBalanceStatus.OVERDUE,
    )
    payable = AccountPayable(
        supplier_id=supplier.id,
        bill_reference="FAC-VENCIDA-001",
        total_amount=Decimal("800.00"),
        paid_amount=Decimal("0.00"),
        due_date=_PAST_DUE,
        status=AccountBalanceStatus.OVERDUE,
    )
    db_session.add_all([receivable, payable])
    db_session.commit()
    db_session.refresh(receivable)
    db_session.refresh(payable)

    ar_list = client.get(
        f"{ACCOUNTING_URL}/receivables",
        headers=accounting_headers,
        params={"status": AccountBalanceStatus.OVERDUE.value},
    )
    assert receivable.id in [item["id"] for item in ar_list.json()]
    due_list = client.get(
        f"{ACCOUNTING_URL}/receivables",
        headers=accounting_headers,
        params={"due_before": date.today().isoformat()},
    )
    assert receivable.id in [item["id"] for item in due_list.json()]

    ap_list = client.get(
        f"{ACCOUNTING_URL}/payables",
        headers=accounting_headers,
        params={"status": AccountBalanceStatus.OVERDUE.value},
    )
    assert payable.id in [item["id"] for item in ap_list.json()]

    # Un abono mantiene OVERDUE mientras quede saldo pendiente.
    assert _pay(
        client, accounting_headers, "400.00", receivable_id=receivable.id
    ).status_code == 201
    partial = client.get(
        f"{ACCOUNTING_URL}/receivables/{receivable.id}", headers=accounting_headers
    )
    assert partial.json()["paid_amount"] == "400.00"
    assert partial.json()["status"] == AccountBalanceStatus.OVERDUE.value

    assert _pay(
        client, accounting_headers, "600.00", receivable_id=receivable.id
    ).status_code == 201
    settled = client.get(
        f"{ACCOUNTING_URL}/receivables/{receivable.id}", headers=accounting_headers
    )
    assert settled.json()["status"] == AccountBalanceStatus.PAID.value
    ar_list = client.get(
        f"{ACCOUNTING_URL}/receivables",
        headers=accounting_headers,
        params={"status": AccountBalanceStatus.OVERDUE.value},
    )
    assert receivable.id not in [item["id"] for item in ar_list.json()]


# --------------------------------------------------------------------------- #
# Reportes financieros (regla 9 y sección 4.6)
# --------------------------------------------------------------------------- #


def test_reports_only_aggregate_posted_entries(
    client: TestClient,
    accounting_headers: dict[str, str],
    chart: dict[str, Account],
    db_session: Session,
) -> None:
    _posted_sale(db_session, chart, "ASI-BDD-REP-1", "1200.00")
    draft = accounting_service.create_journal_entry(
        db_session, _service_payload(chart, "ASI-BDD-REP-DRAFT", "999.00")
    )
    void = accounting_service.create_journal_entry(
        db_session, _service_payload(chart, "ASI-BDD-REP-VOID", "555.00")
    )
    accounting_service.void_journal_entry(db_session, void.id)
    assert draft.status is JournalEntryStatus.DRAFT
    assert void.status is JournalEntryStatus.VOID

    common = {"date_from": _NOV_FROM, "date_to": _NOV_TO}
    trial = _report(client, accounting_headers, "trial-balance", **common)
    assert trial["total_debit"] == "1200.00"
    assert trial["total_credit"] == "1200.00"
    assert {line["debit"] for line in trial["lines"]} == {
        "1200.00",
        "0.00",
    }

    balance = _report(client, accounting_headers, "balance-sheet", **common)
    assert balance["total_assets"] == "1200.00"
    assert balance["total_liabilities"] == "0.00"

    income = _report(client, accounting_headers, "income-statement", **common)
    assert income["total_revenue"] == "1200.00"
    assert income["net_income"] == "1200.00"


def test_reports_respect_date_window_and_accounting_period(
    client: TestClient,
    accounting_headers: dict[str, str],
    chart: dict[str, Account],
    db_session: Session,
) -> None:
    _posted_sale(
        db_session, chart, "ASI-BDD-REP-NOV", "1000.00", entry_date=date(2026, 11, 10)
    )
    _posted_sale(
        db_session, chart, "ASI-BDD-REP-DEC", "700.00", entry_date=date(2026, 12, 10)
    )
    period = AccountingPeriod(
        name="2026-11",
        start_date=date(2026, 11, 1),
        end_date=date(2026, 11, 30),
        is_closed=False,
    )
    db_session.add(period)
    db_session.commit()
    db_session.refresh(period)

    by_period = _report(
        client, accounting_headers, "trial-balance", period_id=period.id
    )
    assert by_period["total_debit"] == "1000.00"
    by_name = _report(
        client, accounting_headers, "trial-balance", period_name="2026-11"
    )
    assert by_name["total_debit"] == "1000.00"
    by_window = _report(
        client,
        accounting_headers,
        "trial-balance",
        date_from=date(2026, 12, 1),
        date_to=date(2026, 12, 31),
    )
    assert by_window["total_debit"] == "700.00"


# --------------------------------------------------------------------------- #
# RBAC y documentación (regla 9)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "path",
    [
        "/accounts",
        "/journal-entries",
        "/receivables",
        "/payables",
        "/payments",
        "/reports/trial-balance",
        "/reports/balance-sheet",
        "/reports/income-statement",
    ],
)
def test_rbac_anonymous_request_is_401(client: TestClient, path: str) -> None:
    response = client.get(f"{ACCOUNTING_URL}{path}")
    assert response.status_code == 401


@pytest.mark.parametrize(
    "method,path",
    [
        ("GET", "/accounts"),
        ("POST", "/accounts"),
        ("PATCH", "/accounts/1"),
        ("DELETE", "/accounts/1"),
        ("GET", "/journal-entries"),
        ("POST", "/journal-entries"),
        ("POST", "/journal-entries/1/post"),
        ("POST", "/journal-entries/1/void"),
        ("POST", "/journal-entries/1/reverse"),
        ("GET", "/receivables"),
        ("POST", "/payments"),
        ("GET", "/payables"),
        ("GET", "/reports/trial-balance"),
        ("GET", "/reports/balance-sheet"),
        ("GET", "/reports/income-statement"),
    ],
)
def test_rbac_role_without_accounting_permission_is_403(
    client: TestClient,
    sales_headers: dict[str, str],
    method: str,
    path: str,
) -> None:
    response = client.request(
        method, f"{ACCOUNTING_URL}{path}", headers=sales_headers, json={}
    )
    assert response.status_code == 403


@pytest.mark.parametrize("headers_name", ["accounting_headers", "admin_headers"])
def test_rbac_authorized_roles_can_access_module(
    request: pytest.FixtureRequest,
    client: TestClient,
    headers_name: str,
) -> None:
    headers: dict[str, str] = request.getfixturevalue(headers_name)
    for path in (
        "/accounts",
        "/journal-entries",
        "/receivables",
        "/payables",
        "/payments",
        "/reports/trial-balance",
        "/reports/balance-sheet",
        "/reports/income-statement",
    ):
        response = client.get(f"{ACCOUNTING_URL}{path}", headers=headers)
        assert response.status_code == 200, response.text


def test_openapi_documents_accounting_routes(client: TestClient) -> None:
    assert client.get("/docs").status_code == 200
    schema = client.get("/openapi.json")
    assert schema.status_code == 200
    paths = schema.json()["paths"]
    for path in (
        "/api/v1/accounting/accounts",
        "/api/v1/accounting/journal-entries",
        "/api/v1/accounting/journal-entries/{entry_id}/post",
        "/api/v1/accounting/receivables",
        "/api/v1/accounting/payables",
        "/api/v1/accounting/payments",
        "/api/v1/accounting/reports/trial-balance",
        "/api/v1/accounting/reports/balance-sheet",
        "/api/v1/accounting/reports/income-statement",
    ):
        assert path in paths
    assert paths["/api/v1/accounting/accounts"]["get"]["security"] == [
        {"HTTPBearer": []}
    ]


# --------------------------------------------------------------------------- #
# Reglas críticas adicionales (5, 6 y 8)
# --------------------------------------------------------------------------- #


def test_rule_06_journal_line_shapes_are_validated(
    client: TestClient,
    accounting_headers: dict[str, str],
    chart: dict[str, Account],
) -> None:
    base = _entry_payload(
        "ASI-BDD-LINEAS",
        chart["cash"].id,
        chart["revenue"].id,
        "100.00",
        "100.00",
    )
    bad_payloads: list[dict[str, Any]] = [
        {**base, "items": base["items"][:1]},
        {
            **base,
            "items": [
                {
                    "account_id": chart["cash"].id,
                    "debit": "10.00",
                    "credit": "10.00",
                },
                base["items"][1],
            ],
        },
        {
            **base,
            "items": [
                {"account_id": chart["cash"].id, "debit": "-1.00"},
                base["items"][1],
            ],
        },
    ]
    for payload in bad_payloads:
        response = client.post(
            f"{ACCOUNTING_URL}/journal-entries",
            headers=accounting_headers,
            json=payload,
        )
        assert response.status_code in (400, 422)


def test_rule_08_account_with_movements_is_deactivated_not_deleted(
    client: TestClient,
    accounting_headers: dict[str, str],
    chart: dict[str, Account],
    db_session: Session,
) -> None:
    draft = _create_entry(client, accounting_headers, "ASI-BDD-MOV", chart)
    assert _post_entry(client, accounting_headers, draft["id"]).status_code == 200

    account_id = chart["cash"].id
    response = client.delete(
        f"{ACCOUNTING_URL}/accounts/{account_id}", headers=accounting_headers
    )
    assert response.status_code == 204
    detail = client.get(
        f"{ACCOUNTING_URL}/accounts/{account_id}", headers=accounting_headers
    )
    assert detail.json()["is_active"] is False
    assert (
        client.get(
            f"{ACCOUNTING_URL}/journal-entries/{draft['id']}",
            headers=accounting_headers,
        ).status_code
        == 200
    )

    with pytest.raises(accounting_service.AccountInUseError):
        accounting_service.delete_account(db_session, account_id)


def test_rule_05_failed_sales_automation_rolls_back_everything(
    db_session: Session,
    chart: dict[str, Account],
    invoice: Invoice,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("fallo forzado al equilibrar el asiento")

    monkeypatch.setattr(accounting_service, "_ensure_balanced", boom)
    with pytest.raises(RuntimeError, match="fallo forzado"):
        accounting_service.post_sales_invoice_accounting(db_session, invoice.id)

    assert _count(db_session, JournalEntry) == 0
    assert _count(db_session, JournalItem) == 0
    assert _count(db_session, AccountReceivable) == 0
