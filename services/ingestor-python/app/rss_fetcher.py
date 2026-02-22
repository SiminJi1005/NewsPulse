import feedparser
from dateutil import parser as dateparser

DEFAULT_FEEDS = [
    ("bbc", "https://feeds.bbci.co.uk/news/rss.xml"),
    ("techcrunch", "https://techcrunch.com/feed/"),
    ("hn", "https://hnrss.org/frontpage"),
]

def fetch_rss(feeds=DEFAULT_FEEDS, limit_per_feed=15):
    items = []
    for source, url in feeds:
        d = feedparser.parse(url)
        for entry in d.entries[:limit_per_feed]:
            published_at = None
            if getattr(entry, "published", None):
                try:
                    published_at = dateparser.parse(entry.published)
                except Exception:
                    published_at = None

            items.append({
                "source": source,
                "title": getattr(entry, "title", "").strip(),
                "url": getattr(entry, "link", "").strip(),
                "summary": getattr(entry, "summary", "")[:5000],
                "published_at": published_at,
            })
    # basic cleanup
    return [x for x in items if x["title"] and x["url"]]