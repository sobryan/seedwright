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
        { name: "signed_up", sql_type: "date" },
      ],
      primary_key: ["id"],
    },
    orders: {
      columns: [
        { name: "id", sql_type: "bigint" },
        { name: "customer_id", sql_type: "bigint" },
        { name: "total", sql_type: "numeric(10,2)" },
        { name: "created_at", sql_type: "timestamp with time zone" },
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
  const [connections, setConnections] = useState<string[]>([]);
  const [sink, setSink] = useState("");
  const [showForm, setShowForm] = useState(false);
  const [name, setName] = useState("demo-shop");
  const [provider, setProvider] = useState("heuristic");
  const [schema, setSchema] = useState(DEMO_SCHEMA);
  const [foreignKeys, setForeignKeys] = useState(DEMO_FKS);
  const [rules, setRules] = useState(DEMO_RULES);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [previews, setPreviews] = useState<Record<string, Record<string, Record<string, unknown>[]>>>({});
  const [browser, setBrowser] = useState<{
    datasetId: string;
    table: string;
    offset: number;
    total: number;
    rows: Record<string, unknown>[];
  } | null>(null);
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
    api
      .listConnections()
      .then((r) => {
        setConnections(r.connections);
        if (r.connections.length > 0) setSink(r.connections[0]);
      })
      .catch(() => setConnections([])); // jdbc-mcp not running -> file export only
  }, [refresh]);

  async function createBlueprint() {
    setBusy("create");
    try {
      await api.createBlueprint({
        name,
        provider,
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

  async function introspectInto() {
    if (!sink) return;
    setBusy("introspect");
    try {
      const result = await api.introspect(sink);
      setSchema(JSON.stringify(result.schema, null, 2));
      setForeignKeys(JSON.stringify(result.foreign_keys ?? {}, null, 2));
      setName(`${sink}-blueprint`);
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(null);
    }
  }

  async function previewBlueprint(blueprintId: string) {
    setBusy(blueprintId);
    try {
      const result = await api.preview(blueprintId, 5);
      setPreviews((p) => ({ ...p, [blueprintId]: result.tables }));
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(null);
    }
  }

  async function browse(datasetId: string, table: string, offset = 0) {
    setBusy(datasetId);
    try {
      const page = await api.readRows(datasetId, table, offset, 10);
      setBrowser({ datasetId, table, offset, total: page.total_rows, rows: page.rows });
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(null);
    }
  }

  async function materialize(datasetId: string) {
    if (!sink) return;
    // FR-G.4: writing to a database is side-effecting — explicit user confirmation
    if (!confirm(`Load this dataset into database connection "${sink}"?`)) return;
    setBusy(datasetId);
    try {
      const { jobId } = await api.materialize(datasetId, sink);
      pollJob(jobId);
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(null);
    }
  }

  async function reviewAndApprove(blueprintId: string) {
    setBusy(blueprintId);
    try {
      // FR-L.5: show the human the exact artifacts they're vouching for, then capture
      // a named approval — this is what gates any write into a real database.
      const a = await api.getArtifacts(blueprintId);
      const summary = JSON.stringify(a.artifacts, null, 2);
      const approvedBy = prompt(
        `Review generator artifacts ${a.artifactsVersion} (${a.approval}).\n\n` +
          `${summary.slice(0, 1200)}${summary.length > 1200 ? "\n…(truncated)" : ""}\n\n` +
          `Approving authorizes loading data built from these artifacts into a real ` +
          `database. Enter your name to approve, or cancel.`,
      );
      if (!approvedBy || !approvedBy.trim()) return;
      await api.approveArtifacts(blueprintId, approvedBy.trim());
      await refresh();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(null);
    }
  }

  async function teardown(datasetId: string, connection: string) {
    if (!confirm(`Tear this dataset down from "${connection}"? (deletes its ds_ schema)`)) return;
    setBusy(datasetId);
    try {
      const { jobId } = await api.teardown(datasetId, connection);
      pollJob(jobId);
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
          {connections.length > 0 && (
            <div className="row" style={{ marginBottom: "0.8rem" }}>
              <select value={sink} onChange={(e) => setSink(e.target.value)}
                      style={{ padding: "0.4rem", borderRadius: 6 }}>
                {connections.map((c) => (
                  <option key={c} value={c}>{c}</option>
                ))}
              </select>
              <button className="secondary" onClick={introspectInto}
                      disabled={busy === "introspect"}>
                introspect this database → prefill
              </button>
            </div>
          )}
          <label>name</label>
          <input value={name} onChange={(e) => setName(e.target.value)} />
          <label>authoring provider</label>
          <select value={provider} onChange={(e) => setProvider(e.target.value)}
                  style={{ padding: "0.45rem", borderRadius: 6, marginBottom: "0.6rem" }}>
            <option value="heuristic">heuristic — deterministic, no LLM</option>
            <option value="copilot-cli">copilot-cli — GitHub Copilot authors the generator</option>
          </select>
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
              {bp.artifactsVersion && <code className="muted">{bp.artifactsVersion}</code>}{" "}
              {bp.artifactsVersion && (
                <span className="badge"
                      style={{ background: bp.artifactsApproval === "approved" ? "#1a7f37" : "#9a6700" }}
                      title={bp.artifactsApprovedBy ? `approved by ${bp.artifactsApprovedBy}` : ""}>
                  {bp.artifactsApproval === "approved"
                    ? `approved · ${bp.artifactsApprovedBy}`
                    : "pending approval"}
                </span>
              )}
            </div>
            <span className="row">
              {bp.artifactsVersion && bp.artifactsApproval !== "approved" && (
                <button className="secondary" onClick={() => reviewAndApprove(bp.id)}
                        disabled={busy === bp.id}>
                  review & approve
                </button>
              )}
              <button className="secondary" onClick={() => previewBlueprint(bp.id)}
                      disabled={busy === bp.id}>
                preview
              </button>
              <button onClick={() => generate(bp.id)} disabled={busy === bp.id}>
                generate dataset
              </button>
            </span>
          </div>
          {previews[bp.id] &&
            Object.entries(previews[bp.id]).map(([table, rows]) => (
              <div key={table} style={{ marginTop: "0.6rem", overflowX: "auto" }}>
                <div className="muted">{table} (sample)</div>
                <table style={{ borderCollapse: "collapse", fontSize: "0.78rem" }}>
                  <thead>
                    <tr>
                      {rows[0] &&
                        Object.keys(rows[0]).map((col) => (
                          <th key={col} style={{ padding: "0.2rem 0.6rem", textAlign: "left",
                                                 borderBottom: "1px solid var(--border)" }}>
                            {col}
                          </th>
                        ))}
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((row, i) => (
                      <tr key={i}>
                        {Object.values(row).map((v, j) => (
                          <td key={j} style={{ padding: "0.2rem 0.6rem" }}>
                            <code>{String(v)}</code>
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ))}
          {(datasets[bp.id] ?? []).map((ds) => (
            <div className="row spread" key={ds.id} style={{ marginTop: "0.6rem" }}>
              <div>
                <span className={`badge ${ds.status}`}>{ds.status}</span>{" "}
                <code className="muted">{ds.namespace}</code>{" "}
                {ds.rowCounts &&
                  Object.entries(ds.rowCounts).map(([table, count]) => (
                    <button key={table} className="secondary"
                            style={{ marginRight: "0.3rem", padding: "0.15rem 0.5rem",
                                     fontSize: "0.75rem" }}
                            onClick={() => browse(ds.id, table, 0)}>
                      {table}: {count} ▸
                    </button>
                  ))}
              </div>
              {ds.status === "ready" && (
                <span className="row">
                  {connections.length > 0 && (
                    <>
                      <select value={sink} onChange={(e) => setSink(e.target.value)}
                              style={{ padding: "0.4rem", borderRadius: 6 }}>
                        {connections.map((c) => (
                          <option key={c} value={c}>{c}</option>
                        ))}
                      </select>
                      <button onClick={() => materialize(ds.id)}
                              disabled={busy === ds.id || bp.artifactsApproval !== "approved"}
                              title={bp.artifactsApproval !== "approved"
                                ? "approve the generator artifacts first (FR-L.5)" : ""}>
                        load to db
                      </button>
                    </>
                  )}
                  <button
                    className="secondary"
                    onClick={() => exportFiles(ds.id)}
                    disabled={busy === ds.id}
                  >
                    export files
                  </button>
                </span>
              )}
            </div>
          ))}
          {(datasets[bp.id] ?? []).flatMap((ds) =>
            (ds.materializations ?? []).map((m, i) => (
              <div className="row spread" key={ds.id + i} style={{ marginTop: "0.4rem" }}>
                <div className="muted">
                  ↳ <span className={`badge ${m.status === "loaded" ? "ready" : ""}`}>{m.status}</span>{" "}
                  {m.connection} <code>{m.namespace}</code>
                </div>
                {m.status === "loaded" && (
                  <button className="secondary" onClick={() => teardown(ds.id, m.connection)}>
                    teardown
                  </button>
                )}
              </div>
            )),
          )}
        </div>
      ))}

      {browser && (
        <div className="card">
          <div className="row spread">
            <h2>
              {browser.table} — rows {browser.offset + 1}–
              {Math.min(browser.offset + browser.rows.length, browser.total)} of {browser.total}
            </h2>
            <span className="row">
              <button className="secondary" disabled={browser.offset === 0}
                      onClick={() => browse(browser.datasetId, browser.table,
                                            Math.max(0, browser.offset - 10))}>
                ◂ prev
              </button>
              <button className="secondary"
                      disabled={browser.offset + browser.rows.length >= browser.total}
                      onClick={() => browse(browser.datasetId, browser.table,
                                            browser.offset + 10)}>
                next ▸
              </button>
              <button className="secondary" onClick={() => setBrowser(null)}>close</button>
            </span>
          </div>
          <div style={{ overflowX: "auto" }}>
            <table style={{ borderCollapse: "collapse", fontSize: "0.78rem" }}>
              <thead>
                <tr>
                  {browser.rows[0] &&
                    Object.keys(browser.rows[0]).map((col) => (
                      <th key={col} style={{ padding: "0.2rem 0.6rem", textAlign: "left",
                                             borderBottom: "1px solid var(--border)" }}>
                        {col}
                      </th>
                    ))}
                </tr>
              </thead>
              <tbody>
                {browser.rows.map((row, i) => (
                  <tr key={i}>
                    {Object.values(row).map((v, j) => (
                      <td key={j} style={{ padding: "0.2rem 0.6rem" }}>
                        <code>{String(v)}</code>
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </>
  );
}
