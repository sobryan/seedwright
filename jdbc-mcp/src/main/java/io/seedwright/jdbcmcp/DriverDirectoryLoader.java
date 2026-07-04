package io.seedwright.jdbcmcp;

import java.io.IOException;
import java.net.URL;
import java.net.URLClassLoader;
import java.nio.file.Files;
import java.nio.file.Path;
import java.sql.Connection;
import java.sql.Driver;
import java.sql.DriverManager;
import java.sql.DriverPropertyInfo;
import java.sql.SQLException;
import java.sql.SQLFeatureNotSupportedException;
import java.util.ArrayList;
import java.util.List;
import java.util.Properties;
import java.util.ServiceLoader;
import java.util.stream.Stream;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/**
 * Loads JDBC driver jars dropped into a directory (default {@code ./drivers}) — the "unspecified
 * dialect" story: add the vendor's jar (DB2's {@code jcc}, Oracle's {@code ojdbc}, ...), use its
 * JDBC URL in a named connection, done. No rebuild.
 *
 * <p>DriverManager refuses drivers whose class comes from a child classloader, so each
 * discovered {@link Driver} is registered behind a same-classloader shim (the classic
 * DriverShim pattern).
 */
public class DriverDirectoryLoader {

    private static final Logger log = LoggerFactory.getLogger(DriverDirectoryLoader.class);

    private final List<String> registered = new ArrayList<>();

    public DriverDirectoryLoader(Path driverDir) {
        if (!Files.isDirectory(driverDir)) {
            log.info("no driver directory at {} — built-in drivers only", driverDir);
            return;
        }
        try (Stream<Path> files = Files.list(driverDir)) {
            URL[] jars = files
                    .filter(p -> p.getFileName().toString().endsWith(".jar"))
                    .map(DriverDirectoryLoader::toUrl)
                    .toArray(URL[]::new);
            if (jars.length == 0) {
                return;
            }
            @SuppressWarnings("resource") // classloader must outlive us: drivers stay registered
            URLClassLoader loader = new URLClassLoader(jars, getClass().getClassLoader());
            for (Driver driver : ServiceLoader.load(Driver.class, loader)) {
                // only register drivers actually coming from the dropped-in jars
                if (driver.getClass().getClassLoader() == loader) {
                    DriverManager.registerDriver(new DriverShim(driver));
                    registered.add(driver.getClass().getName());
                    log.info("registered JDBC driver from driver dir: {}",
                            driver.getClass().getName());
                }
            }
        } catch (IOException | SQLException e) {
            log.warn("failed loading driver directory {}: {}", driverDir, e.toString());
        }
    }

    public List<String> registeredDrivers() {
        return List.copyOf(registered);
    }

    private static URL toUrl(Path path) {
        try {
            return path.toUri().toURL();
        } catch (IOException e) {
            throw new IllegalArgumentException("bad driver jar path: " + path, e);
        }
    }

    /** Same-classloader delegate so DriverManager accepts a child-classloader driver. */
    static final class DriverShim implements Driver {
        private final Driver delegate;

        DriverShim(Driver delegate) {
            this.delegate = delegate;
        }

        @Override
        public Connection connect(String url, Properties info) throws SQLException {
            return delegate.connect(url, info);
        }

        @Override
        public boolean acceptsURL(String url) throws SQLException {
            return delegate.acceptsURL(url);
        }

        @Override
        public DriverPropertyInfo[] getPropertyInfo(String url, Properties info)
                throws SQLException {
            return delegate.getPropertyInfo(url, info);
        }

        @Override
        public int getMajorVersion() {
            return delegate.getMajorVersion();
        }

        @Override
        public int getMinorVersion() {
            return delegate.getMinorVersion();
        }

        @Override
        public boolean jdbcCompliant() {
            return delegate.jdbcCompliant();
        }

        @Override
        public java.util.logging.Logger getParentLogger() throws SQLFeatureNotSupportedException {
            return delegate.getParentLogger();
        }
    }
}
