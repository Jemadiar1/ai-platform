export type TenantId = string;

export interface ApiResponse<T> {
  data: T | null;
  error: string | null;
  meta: Record<string, unknown>;
}

export interface TaskRecord {
  id: string;
  tenant_id: TenantId;
  module: string;
  status: "queued" | "running" | "completed" | "failed";
}

