package io.seedwright.server;

import static org.assertj.core.api.Assertions.assertThat;

import io.seedwright.server.domain.BlueprintEntity;
import io.seedwright.server.domain.BlueprintRepository;
import io.seedwright.server.engine.DataEngine;
import java.nio.file.Path;
import java.time.Instant;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.boot.builder.SpringApplicationBuilder;
import org.springframework.context.ConfigurableApplicationContext;

/**
 * THE requirement this metadata store was chosen for: H2 file mode persists past restarts.
 * Boot the app against a file DB, write a Blueprint, shut the context down completely, boot a
 * fresh context on the same file, and the Blueprint is still there.
 */
class PersistenceAcrossRestartTest {

    @TempDir
    Path tempDir;

    private ConfigurableApplicationContext boot(Path dbDir) {
        return new SpringApplicationBuilder(SeedwrightServerApplication.class)
                .properties(
                        "spring.datasource.url=jdbc:h2:file:" + dbDir.resolve("seedwright")
                                + ";DB_CLOSE_ON_EXIT=FALSE",
                        "server.port=0",
                        "seedwright.work-dir=" + dbDir.resolve("work"))
                .initializers(ctx -> ctx.getBeanFactory()
                        .registerSingleton("dataEngine", (DataEngine) new FakeDataEngine()))
                .run();
    }

    @Test
    void blueprintSurvivesFullRestart() {
        String id;
        try (ConfigurableApplicationContext first = boot(tempDir)) {
            BlueprintRepository repo = first.getBean(BlueprintRepository.class);
            BlueprintEntity entity = new BlueprintEntity();
            entity.setId("bp-restart-test");
            entity.setName("survives");
            entity.setStatus("draft");
            entity.setSeed(42);
            entity.setSchemaJson("{}");
            entity.setCreatedAt(Instant.now());
            entity.setUpdatedAt(Instant.now());
            repo.save(entity);
            id = entity.getId();
        } // context fully closed = the JVM's connection to the file store is gone

        try (ConfigurableApplicationContext second = boot(tempDir)) {
            BlueprintRepository repo = second.getBean(BlueprintRepository.class);
            assertThat(repo.findById(id))
                    .isPresent()
                    .get()
                    .extracting(BlueprintEntity::getName)
                    .isEqualTo("survives");
        }
    }
}
