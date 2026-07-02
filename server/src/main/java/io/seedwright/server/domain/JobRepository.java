package io.seedwright.server.domain;

import java.util.List;
import org.springframework.data.jpa.repository.JpaRepository;

public interface JobRepository extends JpaRepository<JobEntity, String> {
    List<JobEntity> findByStatus(String status);
}
