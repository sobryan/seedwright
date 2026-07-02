package io.seedwright.server;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.boot.context.properties.ConfigurationPropertiesScan;

/**
 * seedwright central server (ADR-0004): REST API + H2 file-mode metadata (persists restarts) +
 * job orchestration + MCP client to the Python data-engine (stdio) and the JDBC loader (HTTP).
 */
@SpringBootApplication
@ConfigurationPropertiesScan
public class SeedwrightServerApplication {

    public static void main(String[] args) {
        SpringApplication.run(SeedwrightServerApplication.class, args);
    }
}
