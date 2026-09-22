from trendradar.collect import canonicalize_url, extract_article, parse_datetime


def test_canonical_url_drops_tracking():
    url = canonicalize_url("https://Example.com/a/?utm_source=x&foo=1#bar")
    assert url == "https://example.com/a?foo=1"


def test_extract_article_metadata():
    html = """
    <html><head>
      <meta property="og:title" content="Company doubles enterprise revenue">
      <meta name="description" content="A useful description">
      <meta property="article:published_time" content="2026-09-21T08:00:00Z">
    </head><body><article>
      <p>This is a sufficiently long business paragraph describing customers and revenue growth.</p>
    </article></body></html>
    """
    title,summary,content,published = extract_article(html,"fallback")
    assert title == "Company doubles enterprise revenue"
    assert summary == "A useful description"
    assert "business paragraph" in content
    assert published is not None


def test_parse_datetime_invalid_is_none():
    assert parse_datetime("not-a-date") is None
