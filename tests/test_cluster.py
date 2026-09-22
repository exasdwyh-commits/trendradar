from trendradar.cluster import cluster_titles, similarity


def test_similar_titles_cluster():
    rows = [
        ("1", "OpenAI signs major enterprise contract with retailer"),
        ("2", "Retailer signs major enterprise contract with OpenAI"),
        ("3", "Robot factory opens new production line in China"),
    ]
    clusters = cluster_titles(rows, threshold=0.35)
    assert len(clusters) == 2


def test_unrelated_titles_low_similarity():
    assert similarity("AI agent cuts invoice processing cost", "Copper prices rise after mine closure") < 0.3
