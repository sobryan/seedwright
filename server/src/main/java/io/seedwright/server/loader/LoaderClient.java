package io.seedwright.server.loader;

import java.util.List;
import java.util.Map;

/**
 * Port to the JDBC loader MCP server (ADR-0004). Connections are referenced by NAME — the
 * loader node holds the credentials (spec §7); they never appear here. The MCP implementation
 * dials the node over Streamable HTTP; tests substitute a fake.
 */
public interface LoaderClient {

    List<String> listConnections();

    Map<String, Object> introspectSchema(String connection, String schemaPattern);

    Map<String, Object> loadDataset(String connection, String dataDir,
                                    Map<String, Object> loadPlan, String namespace, String mode);

    Map<String, Object> teardownDataset(String connection, String namespace);

    Map<String, Object> verifyMaterialization(String connection, Map<String, Object> loadPlan,
                                              String namespace);
}
