package com.newspulse.api;

import co.elastic.clients.elasticsearch.ElasticsearchClient;
import co.elastic.clients.elasticsearch.core.SearchResponse;
import co.elastic.clients.elasticsearch.core.search.Hit;
import co.elastic.clients.elasticsearch._types.query_dsl.Query;
import co.elastic.clients.elasticsearch._types.query_dsl.MultiMatchQuery;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.web.bind.annotation.*;

import java.util.*;

@RestController
@CrossOrigin(origins = "*")
public class ApiController {

    private final ElasticsearchClient es;
    private final ArticleRepository repo;
    private final String index;

    public ApiController(ElasticsearchClient es,
                         ArticleRepository repo,
                         @Value("${newspulse.elasticsearch.index}") String index) {
        this.es = es;
        this.repo = repo;
        this.index = index;
    }

    @GetMapping("/health")
    public Map<String, Object> health() {
        return Map.of("status", "ok");
    }

    @GetMapping("/articles/{id}")
    public ArticleEntity getArticle(@PathVariable Long id) {
        return repo.findById(id).orElseThrow();
    }

    @GetMapping("/search")
    public Map<String, Object> search(
            @RequestParam String q,
            @RequestParam(required = false) String source,
            @RequestParam(defaultValue = "0") int from,
            @RequestParam(defaultValue = "10") int size
    ) throws Exception {

        Query mm = MultiMatchQuery.of(m -> m
                .query(q)
                .fields("title", "summary")
        )._toQuery();

        Query finalQuery;
        if (source != null && !source.isBlank()) {
            finalQuery = Query.of(qb -> qb
                    .bool(b -> b
                            .must(mm)
                            .filter(f -> f.term(t -> t.field("source").value(source)))
                    )
            );
        } else {
            finalQuery = mm;
        }

        SearchResponse<Map> resp = es.search(s -> s
                        .index(index)
                        .query(finalQuery)
                        .from(from)
                        .size(size),
                Map.class);

        List<Map<String, Object>> hits = new ArrayList<>();
        for (Hit<Map> h : resp.hits().hits()) {
            Map src = h.source();
            if (src == null) continue;
            Map<String, Object> item = new HashMap<>();
            item.put("id", src.get("id"));
            item.put("title", src.get("title"));
            item.put("summary", src.get("summary"));
            item.put("source", src.get("source"));
            item.put("url", src.get("url"));
            item.put("published_at", src.get("published_at"));
            hits.add(item);
        }

        return Map.of(
                "total", resp.hits().total() != null ? resp.hits().total().value() : hits.size(),
                "from", from,
                "size", size,
                "results", hits
        );
    }
}
