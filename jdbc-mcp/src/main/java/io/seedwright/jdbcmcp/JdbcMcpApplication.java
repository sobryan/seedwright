package io.seedwright.jdbcmcp;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.boot.autoconfigure.jdbc.DataSourceAutoConfiguration;
import org.springframework.boot.context.properties.ConfigurationPropertiesScan;

/**
 * seedwright JDBC MCP server (ADR-0004): schema introspection + scoped dataset load/teardown
 * over JDBC, exposed as MCP tools over Streamable HTTP. The central server dials in; this node
 * holds the datastore credentials locally (spec §7) and only ever executes commands it receives.
 * On-prem it listens on localhost; the same artifact later deploys as a relay node next to a
 * remote datastore.
 */
@SpringBootApplication(exclude = DataSourceAutoConfiguration.class)
@ConfigurationPropertiesScan
public class JdbcMcpApplication {

    public static void main(String[] args) {
        SpringApplication.run(JdbcMcpApplication.class, args);
    }
}
