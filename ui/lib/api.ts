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

export interface Dataset {
  id: string;
  blueprintId: string;
  status: string;
  namespace: string;
  rowCounts?: Record<string, number>;
  validationReport?: { passed: boolean; failures: unknown[] };
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
};
