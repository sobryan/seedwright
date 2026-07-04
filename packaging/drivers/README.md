# Drop-in JDBC drivers

Put JDBC driver jars for dialects not built in (Postgres and H2 are built in) here — e.g.
`db2jcc4.jar`, `ojdbc11.jar`, `mssql-jdbc.jar`. The loader node loads every jar in this
directory at startup and registers its drivers, so a matching `jdbc:...` URL in
`conf/jdbc-mcp.yml` just works. Restart after adding a jar.
