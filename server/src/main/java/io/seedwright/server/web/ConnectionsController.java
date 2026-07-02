package io.seedwright.server.web;

import io.seedwright.server.loader.LoaderClient;
import java.util.List;
import java.util.Map;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * Datastore connections, proxied to the jdbc-mcp node (which holds the credentials, spec §7).
 * Introspection returns exactly the schema/foreign_keys shape Blueprint creation consumes —
 * point seedwright at their DB, get a Blueprint starting point (FR-A).
 */
@RestController
@RequestMapping("/api/connections")
public class ConnectionsController {

    private final LoaderClient loader;

    public ConnectionsController(LoaderClient loader) {
        this.loader = loader;
    }

    @GetMapping
    public Map<String, List<String>> list() {
        return Map.of("connections", loader.listConnections());
    }

    @PostMapping("/{name}/introspect")
    public ResponseEntity<Map<String, Object>> introspect(
            @PathVariable String name,
            @RequestParam(required = false) String schema) {
        return ResponseEntity.ok(loader.introspectSchema(name, schema));
    }
}
