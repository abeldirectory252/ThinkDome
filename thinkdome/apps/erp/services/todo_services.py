"""Todo Services for HR, Inventory, CRM, Projects, and Assets.

Provides placeholder methods for non-accounting modules. Returns a clean
not-implemented dict indicating they are part of the future development pipeline.
"""

from __future__ import annotations

from typing import Any, Dict


class HRServiceTodo:
    """HR Service Stub."""

    @staticmethod
    def _stub(method_name: str) -> Dict[str, Any]:
        return {
            "status": "not_implemented",
            "domain": "hr",
            "message": f"HR function '{method_name}' is currently a TODO. Focus is currently on Accounting.",
        }

    def create_employee(self, *args, **kwargs) -> Dict[str, Any]:
        return self._stub("create_employee")

    def get_employee_directory(self, *args, **kwargs) -> Dict[str, Any]:
        return self._stub("get_employee_directory")

    def record_attendance(self, *args, **kwargs) -> Dict[str, Any]:
        return self._stub("record_attendance")

    def get_attendance_report(self, *args, **kwargs) -> Dict[str, Any]:
        return self._stub("get_attendance_report")

    def create_leave_request(self, *args, **kwargs) -> Dict[str, Any]:
        return self._stub("create_leave_request")

    def approve_leave(self, *args, **kwargs) -> Dict[str, Any]:
        return self._stub("approve_leave")

    def get_leave_balance(self, *args, **kwargs) -> Dict[str, Any]:
        return self._stub("get_leave_balance")

    def process_payroll(self, *args, **kwargs) -> Dict[str, Any]:
        return self._stub("process_payroll")

    def get_payroll_report(self, *args, **kwargs) -> Dict[str, Any]:
        return self._stub("get_payroll_report")


class InventoryServiceTodo:
    """Inventory Service Stub."""

    @staticmethod
    def _stub(method_name: str) -> Dict[str, Any]:
        return {
            "status": "not_implemented",
            "domain": "inventory",
            "message": f"Inventory function '{method_name}' is currently a TODO. Focus is currently on Accounting.",
        }

    def create_item(self, *args, **kwargs) -> Dict[str, Any]:
        return self._stub("create_item")

    def create_stock_entry(self, *args, **kwargs) -> Dict[str, Any]:
        return self._stub("create_stock_entry")

    def get_stock_balance(self, *args, **kwargs) -> Dict[str, Any]:
        return self._stub("get_stock_balance")

    def get_stock_ledger(self, *args, **kwargs) -> Dict[str, Any]:
        return self._stub("get_stock_ledger")

    def get_reorder_report(self, *args, **kwargs) -> Dict[str, Any]:
        return self._stub("get_reorder_report")

    def get_stock_valuation(self, *args, **kwargs) -> Dict[str, Any]:
        return self._stub("get_stock_valuation")


class CRMServiceTodo:
    """CRM Service Stub."""

    @staticmethod
    def _stub(method_name: str) -> Dict[str, Any]:
        return {
            "status": "not_implemented",
            "domain": "crm",
            "message": f"CRM function '{method_name}' is currently a TODO. Focus is currently on Accounting.",
        }

    def create_lead(self, *args, **kwargs) -> Dict[str, Any]:
        return self._stub("create_lead")

    def convert_lead_to_opportunity(self, *args, **kwargs) -> Dict[str, Any]:
        return self._stub("convert_lead_to_opportunity")

    def update_opportunity_stage(self, *args, **kwargs) -> Dict[str, Any]:
        return self._stub("update_opportunity_stage")

    def get_sales_pipeline(self, *args, **kwargs) -> Dict[str, Any]:
        return self._stub("get_sales_pipeline")

    def get_customer_ledger(self, *args, **kwargs) -> Dict[str, Any]:
        return self._stub("get_customer_ledger")


class ProjectServiceTodo:
    """Project Service Stub."""

    @staticmethod
    def _stub(method_name: str) -> Dict[str, Any]:
        return {
            "status": "not_implemented",
            "domain": "projects",
            "message": f"Projects function '{method_name}' is currently a TODO. Focus is currently on Accounting.",
        }

    def create_project(self, *args, **kwargs) -> Dict[str, Any]:
        return self._stub("create_project")

    def create_task(self, *args, **kwargs) -> Dict[str, Any]:
        return self._stub("create_task")

    def log_timesheet(self, *args, **kwargs) -> Dict[str, Any]:
        return self._stub("log_timesheet")

    def get_project_profitability(self, *args, **kwargs) -> Dict[str, Any]:
        return self._stub("get_project_profitability")

    def get_resource_utilization(self, *args, **kwargs) -> Dict[str, Any]:
        return self._stub("get_resource_utilization")


class AssetServiceTodo:
    """Asset Service Stub."""

    @staticmethod
    def _stub(method_name: str) -> Dict[str, Any]:
        return {
            "status": "not_implemented",
            "domain": "assets",
            "message": f"Assets function '{method_name}' is currently a TODO. Focus is currently on Accounting.",
        }

    def register_asset(self, *args, **kwargs) -> Dict[str, Any]:
        return self._stub("register_asset")

    def compute_depreciation(self, *args, **kwargs) -> Dict[str, Any]:
        return self._stub("compute_depreciation")

    def get_asset_register(self, *args, **kwargs) -> Dict[str, Any]:
        return self._stub("get_asset_register")

    def get_depreciation_schedule(self, *args, **kwargs) -> Dict[str, Any]:
        return self._stub("get_depreciation_schedule")
