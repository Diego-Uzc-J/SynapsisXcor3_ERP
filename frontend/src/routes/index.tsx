import { createBrowserRouter, Navigate } from "react-router-dom";

import AppLayout from "../layouts/AppLayout";
import ChartOfAccountsPage from "../modules/accounting/ChartOfAccountsPage";
import FinancialReportsPage from "../modules/accounting/FinancialReportsPage";
import JournalEntriesPage from "../modules/accounting/JournalEntriesPage";
import ReceivablesPayablesPage from "../modules/accounting/ReceivablesPayablesPage";
import InventoryPage from "../modules/inventory/InventoryPage";
import ProductList from "../modules/inventory/ProductList";
import WarehouseList from "../modules/inventory/WarehouseList";
import BomDetail from "../modules/manufacturing/BomDetail";
import BomList from "../modules/manufacturing/BomList";
import ProductionOrderDetail from "../modules/manufacturing/ProductionOrderDetail";
import ProductionOrderList from "../modules/manufacturing/ProductionOrderList";
import WorkCenterList from "../modules/manufacturing/WorkCenterList";
import GoodsReceiptList from "../modules/purchasing/GoodsReceiptList";
import AttendancePage from "../modules/hr/AttendancePage";
import ContractsPage from "../modules/hr/ContractsPage";
import EmployeeList from "../modules/hr/EmployeeList";
import EmployeeProfile from "../modules/hr/EmployeeProfile";
import PayrollRunDetail from "../modules/hr/PayrollRunDetail";
import PayrollRunsPage from "../modules/hr/PayrollRunsPage";
import PurchaseOrderList from "../modules/purchasing/PurchaseOrderList";
import SupplierBillDetail from "../modules/purchasing/SupplierBillDetail";
import SupplierBillList from "../modules/purchasing/SupplierBillList";
import SupplierList from "../modules/purchasing/SupplierList";
import CustomerList from "../modules/sales/CustomerList";
import InvoiceDetail from "../modules/sales/InvoiceDetail";
import InvoiceList from "../modules/sales/InvoiceList";
import SalesOrderList from "../modules/sales/SalesOrderList";
import LoginPage from "../modules/users/LoginPage";
import UserList from "../modules/users/UserList";
import AccessDenied from "./AccessDenied";
import { IndexRedirect, RequireAuth, RequireModule, RequireRole } from "./guards";

export const router = createBrowserRouter([
  {
    path: "/login",
    element: <LoginPage />,
  },
  {
    element: <RequireAuth />,
    children: [
      {
        path: "/",
        element: <AppLayout />,
        children: [
          { index: true, element: <IndexRedirect /> },

          {
            element: <RequireModule module="inventory" />,
            children: [
              { path: "inventory", element: <InventoryPage /> },
              { path: "inventory/products", element: <ProductList /> },
              { path: "inventory/warehouses", element: <WarehouseList /> },
            ],
          },

          {
            element: <RequireModule module="users" />,
            children: [{ path: "users", element: <UserList /> }],
          },

          {
            element: <RequireModule module="sales" />,
            children: [
              {
                element: (
                  <RequireRole
                    roles={["sales", "administrator"]}
                    module="sales"
                  />
                ),
                children: [
                  {
                    path: "sales",
                    element: <Navigate to="/sales/customers" replace />,
                  },
                  { path: "sales/customers", element: <CustomerList /> },
                  { path: "sales/orders", element: <SalesOrderList /> },
                  { path: "sales/invoices", element: <InvoiceList /> },
                  {
                    path: "sales/invoices/:invoiceId",
                    element: <InvoiceDetail />,
                  },
                ],
              },
            ],
          },
          {
            element: <RequireModule module="purchasing" />,
            children: [
              {
                element: (
                  <RequireRole
                    roles={["purchasing", "administrator"]}
                    module="purchasing"
                  />
                ),
                children: [
                  {
                    path: "purchasing",
                    element: <Navigate to="/purchasing/suppliers" replace />,
                  },
                  {
                    path: "purchasing/suppliers",
                    element: <SupplierList />,
                  },
                  {
                    path: "purchasing/orders",
                    element: <PurchaseOrderList />,
                  },
                  {
                    path: "purchasing/receipts",
                    element: <GoodsReceiptList />,
                  },
                  {
                    path: "purchasing/bills",
                    element: <SupplierBillList />,
                  },
                  {
                    path: "purchasing/bills/:billId",
                    element: <SupplierBillDetail />,
                  },
                ],
              },
            ],
          },
          {
            element: <RequireModule module="accounting" />,
            children: [
              {
                element: (
                  <RequireRole
                    roles={["accounting", "administrator"]}
                    module="accounting"
                  />
                ),
                children: [
                  {
                    path: "accounting",
                    element: <Navigate to="/accounting/accounts" replace />,
                  },
                  {
                    path: "accounting/accounts",
                    element: <ChartOfAccountsPage />,
                  },
                  {
                    path: "accounting/journal",
                    element: <JournalEntriesPage />,
                  },
                  {
                    path: "accounting/receivables",
                    element: <ReceivablesPayablesPage />,
                  },
                  {
                    path: "accounting/reports",
                    element: <FinancialReportsPage />,
                  },
                ],
              },
            ],
          },
          {
            element: <RequireModule module="hr" />,
            children: [
              {
                element: (
                  <RequireRole
                    roles={["hr", "administrator"]}
                    module="hr"
                  />
                ),
                children: [
                  {
                    path: "hr",
                    element: <Navigate to="/hr/employees" replace />,
                  },
                  { path: "hr/employees", element: <EmployeeList /> },
                  {
                    path: "hr/employees/:employeeId",
                    element: <EmployeeProfile />,
                  },
                  { path: "hr/contracts", element: <ContractsPage /> },
                  { path: "hr/attendance", element: <AttendancePage /> },
                  { path: "hr/payrolls", element: <PayrollRunsPage /> },
                  {
                    path: "hr/payrolls/:payrollRunId",
                    element: <PayrollRunDetail />,
                  },
                ],
              },
            ],
          },
          {
            element: <RequireModule module="manufacturing" />,
            children: [
              {
                element: (
                  <RequireRole
                    roles={["manufacturing", "administrator"]}
                    module="manufacturing"
                  />
                ),
                children: [
                  {
                    path: "manufacturing",
                    element: <Navigate to="/manufacturing/orders" replace />,
                  },
                  {
                    path: "manufacturing/work-centers",
                    element: <WorkCenterList />,
                  },
                  { path: "manufacturing/boms", element: <BomList /> },
                  {
                    path: "manufacturing/boms/:bomId",
                    element: <BomDetail />,
                  },
                  {
                    path: "manufacturing/orders",
                    element: <ProductionOrderList />,
                  },
                  {
                    path: "manufacturing/orders/:orderId",
                    element: <ProductionOrderDetail />,
                  },
                ],
              },
            ],
          },

          { path: "sin-acceso", element: <AccessDenied module={null} /> },
          { path: "*", element: <Navigate to="/" replace /> },
        ],
      },
    ],
  },
]);
