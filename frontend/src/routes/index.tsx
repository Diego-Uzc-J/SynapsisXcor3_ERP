import { createBrowserRouter, Navigate } from "react-router-dom";

import AppLayout from "../layouts/AppLayout";
import ChartOfAccountsPage from "../modules/accounting/ChartOfAccountsPage";
import FinancialReportsPage from "../modules/accounting/FinancialReportsPage";
import JournalEntriesPage from "../modules/accounting/JournalEntriesPage";
import ReceivablesPayablesPage from "../modules/accounting/ReceivablesPayablesPage";
import InventoryPage from "../modules/inventory/InventoryPage";
import ProductList from "../modules/inventory/ProductList";
import WarehouseList from "../modules/inventory/WarehouseList";
import GoodsReceiptList from "../modules/purchasing/GoodsReceiptList";
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
import ModulePlaceholder from "./ModulePlaceholder";

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
                path: "hr",
                element: <ModulePlaceholder module="hr" />,
              },
            ],
          },
          {
            element: <RequireModule module="manufacturing" />,
            children: [
              {
                path: "manufacturing",
                element: <ModulePlaceholder module="manufacturing" />,
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
