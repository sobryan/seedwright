package io.seedwright.server;

import io.seedwright.server.loader.LoaderClient;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;

/** Deterministic in-memory stand-in for the jdbc-mcp node (NFR-TEST). Records calls. */
public class FakeLoaderClient implements LoaderClient {

    public final List<String> calls = new ArrayList<>();

    @Override
    public List<String> listConnections() {
        calls.add("list_connections");
        return List.of("warehouse");
    }

    @Override
    public Map<String, Object> introspectSchema(String connection, String schemaPattern) {
        calls.add("introspect:" + connection);
        return Map.of("schema", Map.of(), "foreign_keys", Map.of());
    }

    @Override
    public Map<String, Object> loadDataset(String connection, String dataDir,
                                           Map<String, Object> loadPlan, String namespace,
                                           String mode) {
        calls.add("load:" + connection + ":" + namespace + ":" + mode);
        return Map.of("namespace", namespace, "mode", mode, "total_rows", 40,
                "tables", Map.of("customers", 40));
    }

    @Override
    public Map<String, Object> teardownDataset(String connection, String namespace) {
        calls.add("teardown:" + connection + ":" + namespace);
        return Map.of("namespace", namespace, "existed", true);
    }

    @Override
    public Map<String, Object> verifyMaterialization(String connection,
                                                     Map<String, Object> loadPlan,
                                                     String namespace) {
        calls.add("verify:" + connection + ":" + namespace);
        return Map.of("namespace", namespace, "ok", true, "tables", List.of());
    }
}
