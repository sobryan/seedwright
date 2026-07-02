"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api, Blueprint, Dataset } from "@/lib/api";

const DEMO_SCHEMA = JSON.stringify(
  {
    customers: {
      columns: [
        { name: "id", sql_type: "bigint" },
        { name: "email", sql_type: "varchar(255)" },
        { name: "tier", sql_type: "varchar(20)" },
        { name: "balance", sql_type: "numeric(12,2)" },
      ],
      primary_key: ["id"],
    },
    orders: {
      columns: [
        { name: "id", sql_type: "bigint" },
        { name: "customer_id", sql_type: "bigint" },
        { name: "total", sql_type: "numeric(10,2)" },
      ],
      primary_key: ["id"],
    },
  },
  null,
  2,
);

const DEMO_FKS = JSON.stringify(
  {
    orders: [
      {
        column: "customer_id",
        references_table: "customers",
        references_column: "id",
        min_per_parent: 0,
        max_per_parent: 5,
      },
    ],
  },
  null,
  2,
);

const DEMO_RULES = JSON.stringify(
  [
    { table: "customers", column: "tier", enum: ["free", "pro", "enterprise"] },
    { table: "orders", column: "total", min_value: "1.00", max_value: "999.99" },
  ],
  null,
  2,
);

export default function Home() {
  const [blueprints, setBlueprints] = useState<Blueprint[]>([]);
  const [datasets, setDatasets] = useState<Record<string, Dataset[]>>({});
  const [showForm, setShowForm] = useState(false);
  const [name, setName] = useState("demo-shop");
  const [schema, setSchema] = useState(DEMO_SCHEMA);
  const [foreignKeys, setForeignKeys] = useState(DEMO_FKS);
  const [rules, setRules] = useState(DEMO_RULES);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const pollers = useRef<Set<string>>(new Set());

  const refresh = useCallback(async () => {
    try {
      const list = await api.listBlueprints();
      setBlueprints(list);
      const byBlueprint: Record<string, Dataset[]> = {};
      for (const bp of list) {
        byBlueprint[bp.id] = await api.listDatasets(bp.id);
      }
      setDatasets(byBlueprint);
      setError(null);
    } catch (e) {
      setError(String(e));
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  async function createBlueprint() {
    setBusy("create");
    try {
      await api.createBlueprint({
        name,
        schema: JSON.parse(schema),
        foreignKeys: JSON.parse(foreignKeys),
        rules: JSON.parse(rules),
        volumes: { customers: 100 },
        seed: 42,
      });
      setShowForm(false);
      await refresh();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(null);
    }
  }

  async function generate(blueprintId: string) {
    setBusy(blueprintId);
    try {
      const { jobId } = await api.triggerGeneration(blueprintId);
      pollJob(jobId);
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(null);
    }
  }

  function pollJob(jobId: string) {
    if (pollers.current.has(jobId)) return;
    pollers.current.add(jobId);
    const interval = setInterval(async () => {
      try {
        const job = await api.getJob(jobId);
        if (job.status === "succeeded" || job.status === "failed") {
          clearInterval(interval);
          pollers.current.delete(jobId);
        }
        await refresh();
      } catch {
        clearInterval(interval);
        pollers.current.delete(jobId);
      }
    }, 1500);
  }

  async function exportFiles(datasetId: string) {
    setBusy(datasetId);
    try {
      const result = await api.exportDataset(datasetId, ["csv", "jsonl", "sql"]);
      alert("Exported:\n" + JSON.stringify(result.files, null, 2));
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(null);
    }
  }

  return (
    <>
      <div className="row spread" style={{ marginBottom: "1rem" }}>
        <h1>Blueprints</h1>
        <button onClick={() => setShowForm(!showForm)} className="secondary">
          {showForm ? "cancel" : "new blueprint"}
        </button>
      </div>

      {error && (
        <div className="card">
          <div className="error">{error}</div>
        </div>
      )}

      {showForm && (
        <div className="card">
          <h2>New Blueprint</h2>
          <label>name</label>
          <input value={name} onChange={(e) => setName(e.target.value)} />
          <label>schema (tables → columns + primary_key)</label>
          <textarea rows={10} value={schema} onChange={(e) => setSchema(e.target.value)} />
          <label>foreign keys</label>
          <textarea rows={5} value={foreignKeys} onChange={(e) => setForeignKeys(e.target.value)} />
          <label>rules (declared intent — enums, ranges)</label>
          <textarea rows={4} value={rules} onChange={(e) => setRules(e.target.value)} />
          <button onClick={createBlueprint} disabled={busy === "create"}>
            create
          </button>
        </div>
      )}

      {blueprints.length === 0 && !showForm && (
        <div className="card muted">
          No blueprints yet. Create one — the form is prefilled with a working customers/orders
          demo (heuristic authoring, no LLM key needed).
        </div>
      )}

      {blueprints.map((bp) => (
        <div className="card" key={bp.id}>
          <div className="row spread">
            <div>
              <strong>{bp.name}</strong>{" "}
              <span className="badge">{bp.status}</span>{" "}
              {bp.artifactsVersion && <code className="muted">{bp.artifactsVersion}</code>}
            </div>
            <button onClick={() => generate(bp.id)} disabled={busy === bp.id}>
              generate dataset
            </button>
          </div>
          {(datasets[bp.id] ?? []).map((ds) => (
            <div className="row spread" key={ds.id} style={{ marginTop: "0.6rem" }}>
              <div>
                <span className={`badge ${ds.status}`}>{ds.status}</span>{" "}
                <code className="muted">{ds.namespace}</code>{" "}
                {ds.rowCounts && (
                  <span className="muted">
                    {Object.entries(ds.rowCounts)
                      .map(([table, count]) => `${table}:${count}`)
                      .join("  ")}
                  </span>
                )}
              </div>
              {ds.status === "ready" && (
                <button
                  className="secondary"
                  onClick={() => exportFiles(ds.id)}
                  disabled={busy === ds.id}
                >
                  export csv/jsonl/sql
                </button>
              )}
            </div>
          ))}
        </div>
      ))}
    </>
  );
}
