package io.seedwright.jdbcmcp;

import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.SQLException;
import java.util.Map;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.stereotype.Component;

/**
 * Named datastore connections, configured ON THIS NODE (spec §7: credentials live in the MCP
 * server, never in the orchestrator or model). Tools reference a connection by name; the DSN and
 * credentials never cross the MCP channel.
 */
@Component
public class ConnectionRegistry {

    /** {@code seedwright.connections.<name>.url|username|password} in this node's config. */
    @ConfigurationProperties(prefix = "seedwright")
    public record ConnectionsProperties(Map<String, Entry> connections) {
        public record Entry(String url, String username, String password) {}

        public ConnectionsProperties {
            if (connections == null) {
                connections = Map.of();
            }
        }
    }

    private final ConnectionsProperties properties;

    /** Depends on the driver loader so dropped-in jars are registered before any connect. */
    public ConnectionRegistry(ConnectionsProperties properties,
                              DriverDirectoryLoader driverLoader) {
        this.properties = properties;
    }

    /** Connection NAMES only — never URLs or credentials (those stay on this node). */
    public java.util.List<String> names() {
        return properties.connections().keySet().stream().sorted().toList();
    }

    public Connection open(String name) throws SQLException {
        ConnectionsProperties.Entry entry = properties.connections().get(name);
        if (entry == null) {
            throw new IllegalArgumentException("unknown connection: " + name
                    + " (configure seedwright.connections." + name + ".url on this node)");
        }
        return DriverManager.getConnection(entry.url(), entry.username(), entry.password());
    }
}
