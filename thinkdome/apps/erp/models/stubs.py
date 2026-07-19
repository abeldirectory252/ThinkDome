"""Stubs for future ERP domains.

Provides model skeleton shapes for domains like HR, Inventory, CRM, Projects,
and Assets to preserve structural consistency, leaving actual operations as TODOs.
"""

from __future__ import annotations

from thinkdome.core.orm.orm import (
    Model,
    StringField,
    IntegerField,
    FloatField,
    BooleanField,
    SelectField,
)


# ── HR Domain Stubs ─────────────────────────────────────────────────────────

class Employee(Model):
    """Employee master stub."""
    employee_name = StringField(required=True)
    department = StringField()
    designation = StringField()
    status = SelectField(choices=["Active", "Left"], default="Active")


class Department(Model):
    """Department org units stub."""
    name = StringField(required=True)
    head = StringField()


class Attendance(Model):
    """Attendance tracker stub."""
    employee_id = StringField(required=True)
    date = StringField(required=True)
    status = SelectField(choices=["Present", "Absent", "Leave"], default="Present")


class LeaveRequest(Model):
    """Leave management stub."""
    employee_id = StringField(required=True)
    from_date = StringField(required=True)
    to_date = StringField(required=True)
    status = SelectField(choices=["Pending", "Approved", "Rejected"], default="Pending")


class Payroll(Model):
    """Payroll ledger stub."""
    employee_id = StringField(required=True)
    month = StringField(required=True)
    year = StringField(required=True)
    net_pay = FloatField(default=0.0)


# ── Inventory Domain Stubs ──────────────────────────────────────────────────

class Item(Model):
    """Item stock item master stub."""
    item_name = StringField(required=True)
    item_group = StringField()
    valuation_rate = FloatField(default=0.0)


class Warehouse(Model):
    """Storage warehouses stub."""
    warehouse_name = StringField(required=True)
    location = StringField()


class StockEntry(Model):
    """Stock ledger moves stub."""
    item_id = StringField(required=True)
    qty = FloatField(default=0.0)
    warehouse = StringField()


# ── CRM Domain Stubs ────────────────────────────────────────────────────────

class Lead(Model):
    """Customer leads stub."""
    lead_name = StringField(required=True)
    email = StringField()
    status = SelectField(choices=["Lead", "Opportunity", "Converted"], default="Lead")


class Opportunity(Model):
    """Deals pipeline stub."""
    lead_id = StringField()
    expected_amount = FloatField(default=0.0)
    stage = StringField()


# ── Projects Domain Stubs ───────────────────────────────────────────────────

class Project(Model):
    """Project trackers stub."""
    project_name = StringField(required=True)
    status = SelectField(choices=["Open", "Closed"], default="Open")
    estimated_cost = FloatField(default=0.0)


class Task(Model):
    """Work break down tasks stub."""
    project_id = StringField(required=True)
    task_name = StringField(required=True)
    status = SelectField(choices=["Todo", "In Progress", "Completed"], default="Todo")


# ── Assets Domain Stubs ─────────────────────────────────────────────────────
# Implemented fully in accounting.py

