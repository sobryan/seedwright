package io.seedwright.server.domain;

import java.util.List;
import org.springframework.data.jpa.repository.JpaRepository;

public interface DatasetRepository extends JpaRepository<DatasetEntity, String> {
    List<DatasetEntity> findByBlueprintIdOrderByCreatedAtDesc(String blueprintId);
}
