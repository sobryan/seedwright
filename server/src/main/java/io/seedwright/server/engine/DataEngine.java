package io.seedwright.server.engine;

import java.util.List;
import java.util.Map;

/**
 * Port to the Python data-engine (ADR-0004). The MCP implementation talks stdio to the spawned
 * seedwright-data-engine process; tests substitute a fake. Shapes are the JSON dicts that cross
 * the MCP boundary — the server treats them as opaque aggregates and persists them whole.
 */
public interface DataEngine {

    Map<String, Object> authorGenerator(Map<String, Object> schema,
                                        List<Map<String, Object>> rules,
                                        Map<String, Object> foreignKeys,
                                        Map<String, Object> volumes,
                                        long seed,
                                        String provider);

    Map<String, Object> generateDataset(Map<String, Object> artifacts,
                                        Map<String, Object> schema,
                                        String outDir,
                                        String namespace);

    Map<String, Object> validateDataset(String canonicalDir,
                                        Map<String, Object> loadPlan,
                                        List<Map<String, Object>> dataTests);

    Map<String, Object> exportDataset(String canonicalDir,
                                      Map<String, Object> loadPlan,
                                      String outDir,
                                      List<String> formats);

    Map<String, Object> previewDataset(Map<String, Object> artifacts,
                                       Map<String, Object> schema,
                                       int rowsPerTable);

    Map<String, Object> readRows(String canonicalDir, String table, int offset, int limit);
}
