package com.newspulse.api;

import co.elastic.clients.elasticsearch.ElasticsearchClient;
import co.elastic.clients.elasticsearch.core.SearchResponse;
import co.elastic.clients.elasticsearch.core.search.Hit;
import co.elastic.clients.elasticsearch._types.query_dsl.Query;
import co.elastic.clients.elasticsearch._types.query_dsl.MultiMatchQuery;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.ZSetOperations;
import org.springframework.web.bind.annotation.*;

import java.time.Duration;
import java.util.*;

@RestController
@CrossOrigin(origins = "*")
public class ApiController {

    private static final Duration CACHE_TTL = Duration.ofSeconds(60);
    private static final String CACHE_PREFIX = "newspulse:search:";
    private static final String TRENDING_KEY = "newspulse:trending";

    private final ElasticsearchClient es;
    private final ArticleRepository repo;
    private final StringRedisTemplate redis;
    private final ObjectMapper objectMapper;
    private final String index;

    public ApiController(ElasticsearchClient es,
                         ArticleRepository repo,
                         StringRedisTemplate redis,
                         ObjectMapper objectMapper,
                         @Value("${newspulse.elasticsearch.index}") String index) {
        this.es = es;
        this.repo = repo;
        this.redis = redis;
        this.objectMapper = objectMapper;
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

    @GetMapping("/trending")
    public Map<String, Object> trending() {
        Set<ZSetOperations.TypedTuple<String>> results =
                redis.opsForZSet().reverseRangeWithScores(TRENDING_KEY, 0, 9);

        List<Map<String, Object>> queries = new ArrayList<>();
        if (results != null) {
            for (ZSetOperations.TypedTuple<String> tuple : results) {
                Map<String, Object> item = new HashMap<>();
                item.put("query", tuple.getValue());
                item.put("count", tuple.getScore() != null ? tuple.getScore().longValue() : 0);
                queries.add(item);
            }
        }
        return Map.of("trending", queries);
    }

    @GetMapping("/search")
    public Map<String, Object> search(
            @RequestParam String q,
            @RequestParam(required = false) String source,
            @RequestParam(defaultValue = "0") int from,
            @RequestParam(defaultValue = "10") int size
    ) throws Exception {

        // Record search query for trending (every search, regardless of cache hit/miss)
        redis.opsForZSet().incrementScore(TRENDING_KEY, q.toLowerCase().trim(), 1);

        // Cache-aside: check Redis first
        String cacheKey = buildCacheKey(q, source, from, size);
        String cached = redis.opsForValue().get(cacheKey);
        if (cached != null) {
            return objectMapper.readValue(cached, new TypeReference<Map<String, Object>>() {});
        }

        // Cache miss: query Elasticsearch
        Map<String, Object> result = queryElasticsearch(q, source, from, size);

        // Write to Redis with TTL
        redis.opsForValue().set(cacheKey, objectMapper.writeValueAsString(result), CACHE_TTL);

        return result;
    }

    private String buildCacheKey(String q, String source, int from, int size) {
        String normalizedSource = (source != null && !source.isBlank()) ? source : "_all";
        return CACHE_PREFIX + q.toLowerCase().trim() + ":" + normalizedSource + ":" + from + ":" + size;
    }

    private Map<String, Object> queryElasticsearch(String q, String source, int from, int size) throws Exception {
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
