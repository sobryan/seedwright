package io.seedwright.jdbcmcp;

import static org.assertj.core.api.Assertions.assertThat;

import java.io.ByteArrayOutputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.sql.Connection;
import java.sql.DriverManager;
import java.util.jar.JarEntry;
import java.util.jar.JarOutputStream;
import javax.tools.JavaCompiler;
import javax.tools.ToolProvider;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

/**
 * The "unspecified dialect" story: drop a vendor's JDBC jar into the drivers directory and its
 * URLs just work — no rebuild. Proven honestly: a fake vendor driver (a class NOT on the test
 * classpath) is compiled and jarred at test time, dropped in, and connected through.
 */
class DriverDirectoryLoaderTest {

    @TempDir
    Path work;

    private static final String DRIVER_SOURCE = """
            package fakedb;
            public class FakeDriver implements java.sql.Driver {
                public java.sql.Connection connect(String url, java.util.Properties info) {
                    if (!acceptsURL(url)) return null;
                    return (java.sql.Connection) java.lang.reflect.Proxy.newProxyInstance(
                        getClass().getClassLoader(),
                        new Class<?>[] { java.sql.Connection.class },
                        (proxy, method, args) -> switch (method.getName()) {
                            case "isValid" -> true;
                            case "isClosed" -> false;
                            case "close" -> null;
                            case "toString" -> "fake-connection";
                            case "hashCode" -> System.identityHashCode(proxy);
                            case "equals" -> proxy == args[0];
                            default -> null;
                        });
                }
                public boolean acceptsURL(String url) { return url.startsWith("jdbc:fakedb:"); }
                public java.sql.DriverPropertyInfo[] getPropertyInfo(String u, java.util.Properties i) {
                    return new java.sql.DriverPropertyInfo[0];
                }
                public int getMajorVersion() { return 1; }
                public int getMinorVersion() { return 0; }
                public boolean jdbcCompliant() { return false; }
                public java.util.logging.Logger getParentLogger() { return null; }
            }
            """;

    private Path buildFakeVendorJar() throws Exception {
        Path src = work.resolve("src/fakedb");
        Files.createDirectories(src);
        Path javaFile = src.resolve("FakeDriver.java");
        Files.writeString(javaFile, DRIVER_SOURCE);
        Path classes = work.resolve("classes");
        Files.createDirectories(classes);

        JavaCompiler compiler = ToolProvider.getSystemJavaCompiler();
        int rc = compiler.run(null, new ByteArrayOutputStream(), new ByteArrayOutputStream(),
                "-d", classes.toString(), javaFile.toString());
        assertThat(rc).isZero();

        Path jar = work.resolve("drivers/fakedb-driver.jar");
        Files.createDirectories(jar.getParent());
        try (JarOutputStream out = new JarOutputStream(Files.newOutputStream(jar))) {
            out.putNextEntry(new JarEntry("fakedb/FakeDriver.class"));
            out.write(Files.readAllBytes(classes.resolve("fakedb/FakeDriver.class")));
            out.closeEntry();
            out.putNextEntry(new JarEntry("META-INF/services/java.sql.Driver"));
            out.write("fakedb.FakeDriver\n".getBytes());
            out.closeEntry();
        }
        return jar.getParent();
    }

    @Test
    void dropsInAVendorJarAndConnectsThroughIt() throws Exception {
        Path driverDir = buildFakeVendorJar();

        DriverDirectoryLoader loader = new DriverDirectoryLoader(driverDir);

        assertThat(loader.registeredDrivers()).containsExactly("fakedb.FakeDriver");
        try (Connection conn = DriverManager.getConnection("jdbc:fakedb:anything")) {
            assertThat(conn.isValid(2)).isTrue();
        }
    }

    @Test
    void missingDirectoryIsANoOp() {
        DriverDirectoryLoader loader =
                new DriverDirectoryLoader(work.resolve("does-not-exist"));
        assertThat(loader.registeredDrivers()).isEmpty();
    }
}
