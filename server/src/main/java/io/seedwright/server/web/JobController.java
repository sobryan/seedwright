package io.seedwright.server.web;

import io.seedwright.server.domain.JobEntity;
import io.seedwright.server.domain.JobRepository;
import java.util.LinkedHashMap;
import java.util.Map;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/jobs")
public class JobController {

    private final JobRepository jobs;

    public JobController(JobRepository jobs) {
        this.jobs = jobs;
    }

    @GetMapping("/{id}")
    public ResponseEntity<Map<String, Object>> get(@PathVariable String id) {
        return jobs.findById(id)
                .map(job -> ResponseEntity.ok(toDto(job)))
                .orElse(ResponseEntity.notFound().build());
    }

    private Map<String, Object> toDto(JobEntity job) {
        Map<String, Object> dto = new LinkedHashMap<>();
        dto.put("id", job.getId());
        dto.put("type", job.getType());
        dto.put("status", job.getStatus());
        dto.put("blueprintId", job.getBlueprintId());
        dto.put("datasetId", job.getDatasetId());
        dto.put("message", job.getMessage());
        dto.put("error", job.getError());
        dto.put("createdAt", job.getCreatedAt());
        dto.put("startedAt", job.getStartedAt());
        dto.put("finishedAt", job.getFinishedAt());
        return dto;
    }
}
