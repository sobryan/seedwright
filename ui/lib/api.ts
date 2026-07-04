// REST client for the seedwright central server. Same-origin in production (the Spring server
// serves this UI); NEXT_PUBLIC_API_BASE points elsewhere in development (next dev on :3000,
// server on :8080).

const BASE = process.env.NEXT_PUBLIC_API_BASE ?? "";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!response.ok) {
    const body = await response.text();
    throw new Error(`${response.status} ${response.statusText}: ${body}`);
  }
  return (await response.json()) as T;
}

export interface Blueprint {
  id: string;
  name: string;
  description?: string;
  status: string;
  seed: number;
  artifactsVersion?: string;
  schema: Record<string, unknown>;
}

export interface Job {
  id: string;
  status: string;
  message?: string;
  error?: string;
  datasetId?: string;
}

export interface Materialization {
  connection: string;
  namespace: string;
  status: string;
  verified?: boolean;
  at: string;
}

export interface Dataset {
  id: string;
  blueprintId: string;
  status: string;
  namespace: string;
  rowCounts?: Record<string, number>;
  validationReport?: { passed: boolean; failures: unknown[] };
  materializations?: Materialization[];
}

export const api = {
  listBlueprints: () => request<Blueprint[]>("/api/blueprints"),
  createBlueprint: (body: unknown) =>
    request<Blueprint>("/api/blueprints", { method: "POST", body: JSON.stringify(body) }),
  triggerGeneration: (blueprintId: string) =>
    request<{ jobId: string; datasetId: string }>(`/api/blueprints/${blueprintId}/datasets`, {
      method: "POST",
      body: JSON.stringify({}),
    }),
  getJob: (id: string) => request<Job>(`/api/jobs/${id}`),
  getDataset: (id: string) => request<Dataset>(`/api/datasets/${id}`),
  listDatasets: (blueprintId: string) =>
    request<Dataset[]>(`/api/blueprints/${blueprintId}/datasets`),
  exportDataset: (id: string, formats: string[]) =>
    request<{ files: Record<string, string[]> }>(`/api/datasets/${id}/export`, {
      method: "POST",
      body: JSON.stringify({ formats }),
    }),
  listConnections: () =>
    request<{ connections: string[] }>("/api/connections"),
  introspect: (connection: string) =>
    request<{ schema: Record<string, unknown>; foreign_keys: Record<string, unknown> }>(
      `/api/connections/${connection}/introspect`,
      { method: "POST" },
    ),
  preview: (blueprintId: string, rows = 5) =>
    request<{ sampled: boolean; tables: Record<string, Record<string, unknown>[]> }>(
      `/api/blueprints/${blueprintId}/preview?rows=${rows}`,
      { method: "POST", body: "{}" },
    ),
  readRows: (datasetId: string, table: string, offset: number, limit: number) =>
    request<{ total_rows: number; rows: Record<string, unknown>[] }>(
      `/api/datasets/${datasetId}/rows?table=${encodeURIComponent(table)}&offset=${offset}&limit=${limit}`,
    ),
  materialize: (id: string, connection: string) =>
    request<{ jobId: string }>(`/api/datasets/${id}/materialize`, {
      method: "POST",
      // confirm:true is the explicit FR-G.4 gate — the UI asks the user first
      body: JSON.stringify({ connection, mode: "replace", confirm: true }),
    }),
  teardown: (id: string, connection: string) =>
    request<{ jobId: string }>(`/api/datasets/${id}/teardown`, {
      method: "POST",
      body: JSON.stringify({ connection, confirm: true }),
    }),
};
