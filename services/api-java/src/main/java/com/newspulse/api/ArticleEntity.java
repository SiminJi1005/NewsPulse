package com.newspulse.api;

import jakarta.persistence.*;
import java.time.OffsetDateTime;

@Entity
@Table(name = "articles")
public class ArticleEntity {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    private String source;

    @Column(columnDefinition = "TEXT")
    private String title;

    @Column(columnDefinition = "TEXT", unique = true)
    private String url;

    @Column(columnDefinition = "TEXT")
    private String summary;

    private OffsetDateTime publishedAt;

    private OffsetDateTime createdAt;

    public Long getId() { return id; }
    public String getSource() { return source; }
    public String getTitle() { return title; }
    public String getUrl() { return url; }
    public String getSummary() { return summary; }
    public OffsetDateTime getPublishedAt() { return publishedAt; }
    public OffsetDateTime getCreatedAt() { return createdAt; }
}