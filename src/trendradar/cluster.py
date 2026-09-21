from __future__ import annotations

import re
from dataclasses import dataclass


STOP = {
    "the","a","an","to","of","for","and","in","on","with","from","at","by","is","are",
    "this","that","will","new","says","after","as","its","it","be","has","have",
}


def tokens(title: str) -> set[str]:
    english = re.findall(r"[a-z0-9]{2,}", title.lower())
    chinese = re.findall(r"[\u4e00-\u9fff]{2,}", title)
    return {x for x in english if x not in STOP} | set(chinese)


def similarity(a: str, b: str) -> float:
    ta, tb = tokens(a), tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


@dataclass
class SimpleCluster:
    title: str
    item_ids: list[str]


def cluster_titles(rows: list[tuple[str, str]], threshold: float = 0.42) -> list[SimpleCluster]:
    clusters: list[SimpleCluster] = []
    for item_id, title in rows:
        target = None
        best = 0.0
        for cluster in clusters:
            score = similarity(title, cluster.title)
            if score > best:
                best, target = score, cluster
        if target is not None and best >= threshold:
            target.item_ids.append(item_id)
        else:
            clusters.append(SimpleCluster(title=title, item_ids=[item_id]))
    return clusters
