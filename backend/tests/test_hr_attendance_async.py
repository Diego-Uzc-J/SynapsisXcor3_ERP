"""Pruebas asíncronas de asistencia del módulo ``hr`` (spec 4.3).

Ejercitan las variantes ``*_async`` del servicio sobre ``AsyncSession`` con
SQLite en memoria (``aiosqlite``), sin depender del entorno Docker. Cada
escenario se ejecuta con ``asyncio.run`` para no exigir ``pytest-asyncio``.
"""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault("DATABASE_URL", "sqlite://")

from src.core.database import Base  # noqa: E402
from src.modules.hr.models import (  # noqa: E402
    Attendance,
    AttendanceStatus,
    Employee,
)
from src.modules.hr.schemas import (  # noqa: E402
    AttendanceCreate,
    EmployeeCreate,
)
from src.modules.hr.service import (  # noqa: E402
    InvalidAttendanceError,
    ResourceNotFoundError,
    create_attendance_async,
    list_attendance_async,
)

_TODAY = date(2026, 11, 21)


def _engine() -> Any:
    """Motor asíncrono SQLite compartido por la conexión en memoria."""
    return create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )


async def _prepare() -> tuple[Any, async_sessionmaker[AsyncSession]]:
    engine = _engine()
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


async def _dispose(engine: Any) -> None:
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
    await engine.dispose()


def employee_payload(**overrides: Any) -> EmployeeCreate:
    values: dict[str, Any] = {
        "identification_number": "900123456-1",
        "first_name": "Ana",
        "last_name": "Pérez",
        "email": "ana.perez@example.com",
        "phone": None,
        "birth_date": date(1990, 5, 10),
        "hire_date": date(2026, 1, 1),
    }
    values.update(overrides)
    return EmployeeCreate(**values)


def attendance_payload(employee_id: int, **overrides: Any) -> AttendanceCreate:
    values: dict[str, Any] = {
        "employee_id": employee_id,
        "date": _TODAY,
        "status": AttendanceStatus.PRESENT,
        "overtime_hours": Decimal("0.00"),
        "notes": None,
    }
    values.update(overrides)
    return AttendanceCreate(**values)


async def _seed_employees(db: AsyncSession) -> tuple[int, int]:
    """Crea dos empleados con ORM asíncrono, sin mezclar APIs del servicio."""
    employees = [
        Employee(**employee_payload().model_dump()),
        Employee(
            **employee_payload(
                identification_number="900999999-9", email="otro@example.com"
            ).model_dump()
        ),
    ]
    db.add_all(employees)
    await db.commit()
    for employee in employees:
        await db.refresh(employee)
    return employees[0].id, employees[1].id


async def _count_attendance(db: AsyncSession) -> int:
    result = await db.scalars(select(func.count()).select_from(Attendance))
    return int(result.one())


def test_async_create_attendance_persists_decimal_and_validates_employee() -> None:
    async def scenario() -> None:
        engine, factory = await _prepare()
        async with factory() as db:
            with pytest.raises(ResourceNotFoundError):
                await create_attendance_async(db, attendance_payload(employee_id=999))
            assert await _count_attendance(db) == 0

            first, _ = await _seed_employees(db)
            record = await create_attendance_async(
                db,
                attendance_payload(
                    first,
                    status=AttendanceStatus.OVERTIME,
                    overtime_hours=Decimal("3.25"),
                ),
            )
            assert record.id is not None
            assert record.status is AttendanceStatus.OVERTIME
            assert record.overtime_hours == Decimal("3.25")
            assert await _count_attendance(db) == 1
        await _dispose(engine)

    asyncio.run(scenario())


def test_async_attendance_filters_by_employee_date_and_period() -> None:
    async def scenario() -> None:
        engine, factory = await _prepare()
        async with factory() as db:
            first, second = await _seed_employees(db)

            await create_attendance_async(
                db, attendance_payload(first, date=date(2026, 3, 1))
            )
            target = await create_attendance_async(
                db,
                attendance_payload(
                    first,
                    date=date(2026, 3, 15),
                    status=AttendanceStatus.OVERTIME,
                    overtime_hours=Decimal("2.50"),
                ),
            )
            await create_attendance_async(
                db, attendance_payload(first, date=date(2026, 4, 1))
            )
            await create_attendance_async(
                db, attendance_payload(second, date=date(2026, 3, 10))
            )

            by_employee = await list_attendance_async(db, employee_id=first)
            assert len(by_employee) == 3
            assert all(item.employee_id == first for item in by_employee)
            assert [item.date for item in by_employee] == [
                date(2026, 3, 1),
                date(2026, 3, 15),
                date(2026, 4, 1),
            ]

            by_date = await list_attendance_async(db, date=date(2026, 3, 15))
            assert [item.id for item in by_date] == [target.id]

            first_quarter = await list_attendance_async(
                db,
                employee_id=first,
                start_date=date(2026, 3, 1),
                end_date=date(2026, 3, 31),
            )
            assert [item.date for item in first_quarter] == [
                date(2026, 3, 1),
                date(2026, 3, 15),
            ]

            all_employees = await list_attendance_async(
                db,
                start_date=date(2026, 3, 1),
                end_date=date(2026, 3, 31),
            )
            assert len(all_employees) == 3

            combined = await list_attendance_async(
                db,
                employee_id=first,
                date=date(2026, 3, 15),
                start_date=date(2026, 3, 1),
                end_date=date(2026, 3, 31),
            )
            assert [item.id for item in combined] == [target.id]

            with pytest.raises(ResourceNotFoundError):
                await list_attendance_async(db, employee_id=999)
        await _dispose(engine)

    asyncio.run(scenario())


def test_async_attendance_rejects_invalid_range_and_hours() -> None:
    async def scenario() -> None:
        engine, factory = await _prepare()
        async with factory() as db:
            first, _ = await _seed_employees(db)

            with pytest.raises(InvalidAttendanceError):
                await list_attendance_async(
                    db,
                    start_date=date(2026, 3, 31),
                    end_date=date(2026, 3, 1),
                )

            invalid = AttendanceCreate.model_construct(
                employee_id=first,
                date=_TODAY,
                status=AttendanceStatus.OVERTIME,
                overtime_hours=Decimal("-1.00"),
                notes=None,
            )
            with pytest.raises(InvalidAttendanceError):
                await create_attendance_async(db, invalid)
            assert await _count_attendance(db) == 0
        await _dispose(engine)

    asyncio.run(scenario())
