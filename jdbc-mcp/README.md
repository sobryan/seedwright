# seedwright JDBC MCP server

The DB-access node (ADR-0004): schema **introspection** + scoped dataset **load/teardown** over
JDBC, exposed as MCP tools on Streamable HTTP (`:8081/mcp`). The central server dials in;
**credentials live here** (spec §7) as named connections and never cross the MCP channel.
On-prem it runs on the same box; the same artifact later deploys as a relay node next to a
remote datastore.

## Dialects

Resolved automatically from the JDBC product name (`Dialect`), with the divergences kept as
data (`TypeMap`) + bind adaptations (`BindValues`):

| | Postgres | H2 | **DB2 (LUW)** | ANSI fallback (anything else) |
|---|---|---|---|---|
| BOOLEAN | native | native | `SMALLINT` (0/1) | `SMALLINT` (0/1) |
| tz TIMESTAMP | `TIMESTAMP WITH TIME ZONE` | same | `TIMESTAMP` (values normalized to UTC wall time) | same as DB2 |
| unbounded STRING | `TEXT` | `CLOB` | `CLOB` (`VARCHAR` caps at 32672) | `CLOB` |
| JSON / BYTES / UUID | `JSONB`/`BYTEA`/`UUID` | `CLOB`/`VARBINARY`/`UUID` | `CLOB`/`BLOB`/`CHAR(36)` | `CLOB`/`BLOB`/`CHAR(36)` |
| DECIMAL | `NUMERIC(p,s)` everywhere — money never floats | | | |

**Teardown is portable by construction**: tables are enumerated via JDBC metadata and dropped
individually (each schema-qualified into the validated `ds_` namespace), then
`DROP SCHEMA <ns> RESTRICT` — because DB2 has no `DROP SCHEMA ... CASCADE` and an unspecified
dialect can't be assumed to. Ownership-marker guard and namespace validation are unchanged.

## Connecting to DB2

1. Drop IBM's JDBC driver (`jcc-*.jar` / `db2jcc4.jar`) into the **drivers directory**
   (default `./drivers`, configurable via `seedwright.driver-dir`).
2. Add a named connection (least-privilege user; it needs CREATE/DROP SCHEMA for `ds_*`):

```yaml
seedwright:
  connections:
    db2prod:
      url: jdbc:db2://db2host:50000/MYDB
      username: seedwright_loader
      password: ${DB2_PASSWORD}
```

## Any other database ("unspecified dialect")

Same recipe: drop the vendor's JDBC jar into `drivers/`, add the connection with its
`jdbc:` URL. Drivers are discovered via `ServiceLoader` and registered behind a
`DriverManager` shim — no rebuild. Types fall back to the conservative ANSI column and the
portable teardown; introspection works anywhere JDBC metadata does.

## Development

```bash
mvn test            # runs against in-memory H2 (incl. a live MCP initialize)
mvn spring-boot:run # listens on 127.0.0.1:8081
```
