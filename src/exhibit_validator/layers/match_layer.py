from rapidfuzz import fuzz

def normalize(text: str) -> str:
    if not text:
        return ""
    return text.lower().strip()

def score_pair(a: dict, b: dict) -> float:
    """Return a similarity score between 0 and 1, skipping missing fields."""
    scores = []
    weights = []

    if a.get("name") and b.get("name"):
        name_sim = fuzz.token_set_ratio(normalize(a["name"]), normalize(b["name"])) / 100
        scores.append(name_sim)
        weights.append(0.5)

    if a.get("address") and b.get("address"):
        addr_sim = fuzz.token_set_ratio(normalize(a["address"]), normalize(b["address"])) / 100
        scores.append(addr_sim)
        weights.append(0.3)

    if a.get("latitude") and b.get("latitude"):
        lat_diff = abs(a["latitude"] - b["latitude"])
        lng_diff = abs(a["longitude"] - b["longitude"])
        # ~0.001 degree ~ 100m; treat as same spot if below 0.0005
        coord_sim = max(0, 1 - (lat_diff + lng_diff) / 0.001)
        scores.append(coord_sim)
        weights.append(0.2)

    if not scores:
        return 0.0  # no shared fields -> cannot compare

    total_weight = sum(weights)
    return sum(s * w for s, w in zip(scores, weights)) / total_weight

def find_clusters(records: list[dict], threshold: float = 0.75) -> tuple[list[list[str]], list[dict]]:
    """Return duplicate clusters and gray-zone pair flags."""
    n = len(records)
    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x, y):
        parent[find(x)] = find(y)

    pair_flags = []
    for i in range(n):
        for j in range(i + 1, n):
            sim = score_pair(records[i], records[j])
            if sim >= threshold:
                union(i, j)
                if sim < 0.9:
                    pair_flags.append({
                        "pair": [records[i]["id"], records[j]["id"]],
                        "similarity": round(sim, 2),
                        "reason": "Similarity falls in the gray zone.",
                        "suggested_action": "review",
                    })

    clusters = {}
    for i in range(n):
        root = find(i)
        clusters.setdefault(root, []).append(records[i]["id"])

    return [c for c in clusters.values() if len(c) > 1], pair_flags