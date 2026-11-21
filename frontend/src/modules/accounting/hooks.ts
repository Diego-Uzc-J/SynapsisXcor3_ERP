/**
 * Hooks de TanStack Query v5 del módulo de Finanzas y Contabilidad.
 *
 * Las mutaciones invalidan el libro diario, la cartera (CxC/CxP), el historial
 * de pagos y los reportes según corresponda: contabilizar un asiento o registrar
 * un abono genera movimientos contables que cambian saldos y estados financieros.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { QueryClient } from "@tanstack/react-query";

import {
  accountingKeys,
  createAccount,
  createJournalEntry,
  deactivateAccount,
  getAccount,
  getBalanceSheet,
  getIncomeStatement,
  getJournalEntry,
  getPayable,
  getReceivable,
  getTrialBalance,
  listAccounts,
  listJournalEntries,
  listPayables,
  listPayments,
  listReceivables,
  postJournalEntry,
  registerPayablePayment,
  registerPayment,
  registerReceivablePayment,
  reverseJournalEntry,
  updateAccount,
  voidJournalEntry,
} from "./api";
import type {
  Account,
  AccountCreate,
  AccountFilters,
  AccountUpdate,
  JournalEntry,
  JournalEntryCreate,
  JournalEntryFilters,
  JournalEntryPostResponse,
  PayableFilters,
  PaymentCreate,
  PaymentFilters,
  PaymentRecord,
  PaymentRecordRequest,
  ReceivableFilters,
  ReportFilters,
} from "./types";

// --------------------------------------------------------------------------- //
// Invalidación de caché
// --------------------------------------------------------------------------- //

/** Los reportes se recalculan solo con asientos `POSTED`. */
function invalidateReports(queryClient: QueryClient): void {
  void queryClient.invalidateQueries({ queryKey: accountingKeys.reports.all });
}

/** El estado de un asiento afecta al diario y a los estados financieros. */
function invalidateJournalAndReports(queryClient: QueryClient): void {
  void queryClient.invalidateQueries({
    queryKey: accountingKeys.journalEntries.all,
  });
  invalidateReports(queryClient);
}

/**
 * Publicar, anular, revertir o pagar impacta diario, cartera, pagos y reportes.
 *
 * Los prefijos `all` cubren también los listados filtrados y los detalles.
 */
function invalidateLedgers(queryClient: QueryClient): void {
  void queryClient.invalidateQueries({ queryKey: accountingKeys.receivables.all });
  void queryClient.invalidateQueries({ queryKey: accountingKeys.payables.all });
  void queryClient.invalidateQueries({ queryKey: accountingKeys.payments.all });
  invalidateJournalAndReports(queryClient);
}

// --------------------------------------------------------------------------- //
// Consultas — plan de cuentas
// --------------------------------------------------------------------------- //

/** Lista el plan de cuentas con filtros por código, nombre, tipo y estado. */
export function useAccounts(filters: AccountFilters = {}, enabled = true) {
  return useQuery({
    queryKey: accountingKeys.accounts.list(filters),
    queryFn: () => listAccounts(filters),
    enabled,
  });
}

export function useAccount(accountId: number, enabled = true) {
  return useQuery({
    queryKey: accountingKeys.accounts.detail(accountId),
    queryFn: () => getAccount(accountId),
    enabled: enabled && accountId > 0,
  });
}

// --------------------------------------------------------------------------- //
// Consultas — libro diario
// --------------------------------------------------------------------------- //

/** Lista asientos por código, estado y rango de fechas. */
export function useJournalEntries(
  filters: JournalEntryFilters = {},
  enabled = true,
) {
  return useQuery({
    queryKey: accountingKeys.journalEntries.list(filters),
    queryFn: () => listJournalEntries(filters),
    enabled,
  });
}

export function useJournalEntry(entryId: number, enabled = true) {
  return useQuery({
    queryKey: accountingKeys.journalEntries.detail(entryId),
    queryFn: () => getJournalEntry(entryId),
    enabled: enabled && entryId > 0,
  });
}

// --------------------------------------------------------------------------- //
// Consultas — cartera y pagos
// --------------------------------------------------------------------------- //

export function useReceivables(filters: ReceivableFilters = {}, enabled = true) {
  return useQuery({
    queryKey: accountingKeys.receivables.list(filters),
    queryFn: () => listReceivables(filters),
    enabled,
  });
}

export function useReceivable(receivableId: number, enabled = true) {
  return useQuery({
    queryKey: accountingKeys.receivables.detail(receivableId),
    queryFn: () => getReceivable(receivableId),
    enabled: enabled && receivableId > 0,
  });
}

export function usePayables(filters: PayableFilters = {}, enabled = true) {
  return useQuery({
    queryKey: accountingKeys.payables.list(filters),
    queryFn: () => listPayables(filters),
    enabled,
  });
}

export function usePayable(payableId: number, enabled = true) {
  return useQuery({
    queryKey: accountingKeys.payables.detail(payableId),
    queryFn: () => getPayable(payableId),
    enabled: enabled && payableId > 0,
  });
}

/** Historial de cobros y pagos con filtros por fecha, destino y referencia. */
export function usePayments(filters: PaymentFilters = {}, enabled = true) {
  return useQuery({
    queryKey: accountingKeys.payments.list(filters),
    queryFn: () => listPayments(filters),
    enabled,
  });
}

// --------------------------------------------------------------------------- //
// Consultas — reportes financieros
// --------------------------------------------------------------------------- //

/** Cada reporte se consulta solo mientras su pestaña está activa. */
export function useTrialBalance(filters: ReportFilters = {}, enabled = true) {
  return useQuery({
    queryKey: accountingKeys.reports.trialBalance(filters),
    queryFn: () => getTrialBalance(filters),
    enabled,
  });
}

export function useBalanceSheet(filters: ReportFilters = {}, enabled = true) {
  return useQuery({
    queryKey: accountingKeys.reports.balanceSheet(filters),
    queryFn: () => getBalanceSheet(filters),
    enabled,
  });
}

export function useIncomeStatement(filters: ReportFilters = {}, enabled = true) {
  return useQuery({
    queryKey: accountingKeys.reports.incomeStatement(filters),
    queryFn: () => getIncomeStatement(filters),
    enabled,
  });
}

// --------------------------------------------------------------------------- //
// Mutaciones — plan de cuentas
// --------------------------------------------------------------------------- //

/** Registra una cuenta y refresca el catálogo usado por los formularios. */
export function useCreateAccount() {
  const queryClient = useQueryClient();

  return useMutation<Account, Error, AccountCreate>({
    mutationFn: createAccount,
    onSuccess: (account) => {
      queryClient.setQueryData(
        accountingKeys.accounts.detail(account.id),
        account,
      );
      void queryClient.invalidateQueries({
        queryKey: accountingKeys.accounts.all,
      });
    },
  });
}

export interface UpdateAccountVariables {
  accountId: number;
  payload: AccountUpdate;
}

export function useUpdateAccount() {
  const queryClient = useQueryClient();

  return useMutation<Account, Error, UpdateAccountVariables>({
    mutationFn: ({ accountId, payload }) => updateAccount(accountId, payload),
    onSuccess: (account) => {
      queryClient.setQueryData(
        accountingKeys.accounts.detail(account.id),
        account,
      );
      void queryClient.invalidateQueries({
        queryKey: accountingKeys.accounts.all,
      });
      invalidateReports(queryClient);
    },
  });
}

/** Desactiva una cuenta (borrado lógico) sin borrar su historial. */
export function useDeactivateAccount() {
  const queryClient = useQueryClient();

  return useMutation<void, Error, number>({
    mutationFn: deactivateAccount,
    onSuccess: (_data, accountId) => {
      queryClient.removeQueries({
        queryKey: accountingKeys.accounts.detail(accountId),
      });
      void queryClient.invalidateQueries({
        queryKey: accountingKeys.accounts.all,
      });
    },
  });
}

// --------------------------------------------------------------------------- //
// Mutaciones — libro diario
// --------------------------------------------------------------------------- //

/** Crea un borrador; todavía no afecta saldos ni reportes. */
export function useCreateJournalEntry() {
  const queryClient = useQueryClient();

  return useMutation<JournalEntry, Error, JournalEntryCreate>({
    mutationFn: createJournalEntry,
    onSuccess: (entry) => {
      queryClient.setQueryData(
        accountingKeys.journalEntries.detail(entry.id),
        entry,
      );
      void queryClient.invalidateQueries({
        queryKey: accountingKeys.journalEntries.all,
      });
    },
  });
}

/** Contabiliza el asiento: actualiza diario, cartera, pagos y reportes. */
export function usePostJournalEntry() {
  const queryClient = useQueryClient();

  return useMutation<JournalEntryPostResponse, Error, number>({
    mutationFn: postJournalEntry,
    onSuccess: () => {
      invalidateLedgers(queryClient);
    },
  });
}

/** Anula un borrador (`DRAFT`); no altera saldos pero sí el estado del libro. */
export function useVoidJournalEntry() {
  const queryClient = useQueryClient();

  return useMutation<JournalEntry, Error, number>({
    mutationFn: voidJournalEntry,
    onSuccess: (entry) => {
      queryClient.setQueryData(
        accountingKeys.journalEntries.detail(entry.id),
        entry,
      );
      invalidateJournalAndReports(queryClient);
    },
  });
}

/** Revierte un asiento `POSTED` creando y publicando su contrapartida. */
export function useReverseJournalEntry() {
  const queryClient = useQueryClient();

  return useMutation<JournalEntry, Error, number>({
    mutationFn: reverseJournalEntry,
    onSuccess: (entry) => {
      queryClient.setQueryData(
        accountingKeys.journalEntries.detail(entry.id),
        entry,
      );
      invalidateLedgers(queryClient);
    },
  });
}

// --------------------------------------------------------------------------- //
// Mutaciones — pagos y cobros
// --------------------------------------------------------------------------- //

/** Registra un abono indicando en el cuerpo si es a CxC o a CxP. */
export function useRegisterPayment() {
  const queryClient = useQueryClient();

  return useMutation<PaymentRecord, Error, PaymentCreate>({
    mutationFn: registerPayment,
    onSuccess: () => {
      invalidateLedgers(queryClient);
    },
  });
}

export interface RegisterReceivablePaymentVariables {
  receivableId: number;
  payload: PaymentRecordRequest;
}

/** Abona una CxC desde su detalle; actualiza saldo y estado de la cartera. */
export function useRegisterReceivablePayment() {
  const queryClient = useQueryClient();

  return useMutation<
    PaymentRecord,
    Error,
    RegisterReceivablePaymentVariables
  >({
    mutationFn: ({ receivableId, payload }) =>
      registerReceivablePayment(receivableId, payload),
    onSuccess: () => {
      invalidateLedgers(queryClient);
    },
  });
}

export interface RegisterPayablePaymentVariables {
  payableId: number;
  payload: PaymentRecordRequest;
}

/** Paga una CxP desde su detalle; actualiza saldo y estado de la cartera. */
export function useRegisterPayablePayment() {
  const queryClient = useQueryClient();

  return useMutation<PaymentRecord, Error, RegisterPayablePaymentVariables>({
    mutationFn: ({ payableId, payload }) =>
      registerPayablePayment(payableId, payload),
    onSuccess: () => {
      invalidateLedgers(queryClient);
    },
  });
}
