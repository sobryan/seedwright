package io.seedwright.server;

import io.seedwright.server.engine.DataEngine;
import java.util.List;
import java.util.Map;

/** Deterministic in-memory stand-in for the Python data-engine (NFR-TEST). */
public class FakeDataEngine implements DataEngine {

    @Override
    public Map<String, Object> authorGenerator(Map<String, Object> schema,
                                               List<Map<String, Object>> rules,
                                               Map<String, Object> foreignKeys,
                                               Map<String, Object> volumes,
                                               long seed,
                                               String provider) {
        return Map.of(
                "version", "ga_fake0000",
                "genspec", Map.of("genspec_version", "1", "seed", seed),
                "data_tests", List.of(Map.of(
                        "kind", "unique", "table", "customers", "column", "id",
                        "params", Map.of())),
                "provenance", Map.of(
                        "provider_id", provider == null ? "fake" : provider, "iterations", 1,
                        "determinism_gate_passed", true, "genlib_version", "0.0.1",
                        "approval_status", "pending_approval"));
    }

    @Override
    public Map<String, Object> generateDataset(Map<String, Object> artifacts,
                                               Map<String, Object> schema,
                                               String outDir,
                                               String namespace) {
        return Map.of(
                "canonical_dir", outDir,
                "load_plan", Map.of("namespace", namespace, "tables", List.of()),
                "row_counts", Map.of("customers", 40),
                "seed", 42,
                "artifacts_version", artifacts.get("version"));
    }

    @Override
    public Map<String, Object> validateDataset(String canonicalDir,
                                               Map<String, Object> loadPlan,
                                               List<Map<String, Object>> dataTests) {
        return Map.of("passed", true, "tests_run", dataTests.size(), "failures", List.of());
    }

    @Override
    public Map<String, Object> previewDataset(Map<String, Object> artifacts,
                                              Map<String, Object> schema,
                                              int rowsPerTable) {
        return Map.of("sampled", true, "seed", 42,
                "tables", Map.of("customers", List.of(
                        Map.of("id", 1, "balance", "0.10"),
                        Map.of("id", 2, "balance", "9.99"))));
    }

    @Override
    public Map<String, Object> readRows(String canonicalDir, String table, int offset, int limit) {
        return Map.of("table", table, "offset", offset, "limit", limit,
                "total_rows", 40,
                "rows", List.of(Map.of("id", offset + 1, "balance", "1.00")));
    }

    @Override
    public Map<String, Object> exportDataset(String canonicalDir,
                                             Map<String, Object> loadPlan,
                                             String outDir,
                                             List<String> formats) {
        return Map.of("out_dir", outDir, "files", Map.of(), "total_rows", 40);
    }

    @Override
    public Map<String, Object> suggestRules(String canonicalDir, Map<String, Object> loadPlan,
                                            List<Map<String, Object>> existingRules) {
        // one deterministic suggestion the tests can assert on (skipped if already ruled)
        boolean tierRuled = existingRules.stream()
                .anyMatch(r -> "customers".equals(r.get("table")) && "tier".equals(r.get("column")));
        if (tierRuled) {
            return Map.of("suggestions", List.of());
        }
        return Map.of("suggestions", List.of(Map.of(
                "table", "customers", "column", "tier", "kind", "enum",
                "reason", "only 2 distinct values across 40 rows",
                "rule", Map.of("table", "customers", "column", "tier",
                        "enum", List.of("free", "pro")))));
    }
}
