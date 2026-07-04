package io.seedwright.jdbcmcp;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import java.util.Map;
import org.junit.jupiter.api.Test;

class ConnectionRegistryTest {

    private final ConnectionRegistry registry = new ConnectionRegistry(
            new ConnectionRegistry.ConnectionsProperties(Map.of(
                    "warehouse", new ConnectionRegistry.ConnectionsProperties.Entry(
                            "jdbc:h2:mem:x", "sa", ""),
                    "analytics", new ConnectionRegistry.ConnectionsProperties.Entry(
                            "jdbc:h2:mem:y", "sa", ""))),
            new DriverDirectoryLoader(java.nio.file.Path.of("./no-such-driver-dir")));

    @Test
    void namesAreSortedAndCarryNoSecrets() {
        assertThat(registry.names()).containsExactly("analytics", "warehouse");
    }

    @Test
    void unknownConnectionFailsWithActionableMessage() {
        assertThatThrownBy(() -> registry.open("nope"))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("seedwright.connections.nope.url");
    }
}
