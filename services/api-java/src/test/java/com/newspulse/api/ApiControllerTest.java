package com.newspulse.api;

import co.elastic.clients.elasticsearch.ElasticsearchClient;
import co.elastic.clients.elasticsearch.core.SearchResponse;
import co.elastic.clients.elasticsearch.core.search.HitsMetadata;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.ValueOperations;
import org.springframework.data.redis.core.ZSetOperations;
import org.springframework.test.web.servlet.MockMvc;

import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.function.Function;

import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

@WebMvcTest(ApiController.class)
class ApiControllerTest {

    @Autowired MockMvc mockMvc;

    @MockBean ElasticsearchClient es;
    @MockBean ArticleRepository repo;
    @MockBean StringRedisTemplate redis;

    @SuppressWarnings("unchecked")
    final ValueOperations<String, String> valueOps = mock(ValueOperations.class);
    @SuppressWarnings("unchecked")
    final ZSetOperations<String, String> zSetOps = mock(ZSetOperations.class);

    @BeforeEach
    void setUp() {
        when(redis.opsForValue()).thenReturn(valueOps);
        when(redis.opsForZSet()).thenReturn(zSetOps);
    }

    // ── /health ───────────────────────────────────────────────────────────────

    @Test
    void should_return_success_on_health() throws Exception {
        mockMvc.perform(get("/health"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.status").value("ok"));
    }

    // ── /search: happy path ───────────────────────────────────────────────────

    @Test
    @SuppressWarnings("unchecked")
    void should_return_success_when_search_request_is_valid() throws Exception {
        when(valueOps.get(anyString())).thenReturn(null); // cache miss

        SearchResponse<Map> mockResp = mock(SearchResponse.class);
        HitsMetadata<Map> mockHits = mock(HitsMetadata.class);
        when(mockResp.hits()).thenReturn(mockHits);
        when(mockHits.hits()).thenReturn(List.of());
        when(mockHits.total()).thenReturn(null);
        // doReturn avoids generic type mismatch; any(Function.class) disambiguates overload
        doReturn(mockResp).when(es).search(any(Function.class), eq(Map.class));

        mockMvc.perform(get("/search").param("q", "AI"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.total").exists())
                .andExpect(jsonPath("$.results").isArray());

        verify(es, times(1)).search(any(Function.class), eq(Map.class));
    }

    @Test
    void should_return_cached_result_without_calling_es_on_cache_hit() throws Exception {
        String cached = "{\"total\":3,\"from\":0,\"size\":10,\"results\":[]}";
        when(valueOps.get(anyString())).thenReturn(cached);

        mockMvc.perform(get("/search").param("q", "kafka"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.total").value(3));

        // ES must NOT be called when cache hit
        verify(es, never()).search(any(Function.class), any());
    }

    @Test
    void should_record_trending_before_cache_check() throws Exception {
        String cached = "{\"total\":0,\"from\":0,\"size\":10,\"results\":[]}";
        when(valueOps.get(anyString())).thenReturn(cached);

        mockMvc.perform(get("/search").param("q", "OpenAI"))
                .andExpect(status().isOk());

        // Trending must be recorded with lowercase trimmed query
        verify(zSetOps).incrementScore("newspulse:trending", "openai", 1);
    }

    // ── /search: invalid params → 4xx ────────────────────────────────────────

    @Test
    void should_return_400_when_q_param_is_missing() throws Exception {
        mockMvc.perform(get("/search"))          // no ?q=
                .andExpect(status().isBadRequest());

        // Service must NOT be called
        verify(es, never()).search(any(Function.class), any());
    }

    // ── /search: service exception → 5xx ─────────────────────────────────────

    @Test
    void should_return_5xx_when_es_throws_exception() throws Exception {
        when(valueOps.get(anyString())).thenReturn(null);
        doThrow(new RuntimeException("ES cluster down")).when(es).search(any(Function.class), eq(Map.class));

        mockMvc.perform(get("/search").param("q", "AI"))
                .andExpect(status().is5xxServerError());
    }

    // ── /articles/{id} ────────────────────────────────────────────────────────

    @Test
    void should_return_success_when_article_exists() throws Exception {
        ArticleEntity article = new ArticleEntity();
        when(repo.findById(1L)).thenReturn(Optional.of(article));

        mockMvc.perform(get("/articles/1"))
                .andExpect(status().isOk());
    }

    @Test
    void should_return_404_when_article_not_found() throws Exception {
        when(repo.findById(99L)).thenReturn(Optional.empty());

        mockMvc.perform(get("/articles/99"))
                .andExpect(status().isNotFound());
    }

    // ── /trending ─────────────────────────────────────────────────────────────

    @Test
    void should_return_success_with_trending_list() throws Exception {
        when(zSetOps.reverseRangeWithScores(eq("newspulse:trending"), eq(0L), eq(9L)))
                .thenReturn(null);

        mockMvc.perform(get("/trending"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.trending").isArray());
    }
}
