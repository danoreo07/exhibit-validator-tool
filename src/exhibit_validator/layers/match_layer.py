import logging

from rapidfuzz import fuzz

logger = logging.getLogger(__name__)


def normalize(text: str) -> str:
    if not text:
        return ""
    return text.lower().strip()

def score_pair(a: dict, b: dict) -> float:
    """Return a similarity score between 0 and 1, skipping missing fields."""
    scores = []
    weights = []

    if a.get("name") and b.get("name"):
        name_a = normalize(a["name"])
        name_b = normalize(b["name"])
        
        # SAFETY GUARD 1: If the name length difference is too huge, they are likely different
        len_ratio = min(len(name_a), len(name_b)) / max(len(name_a), len(name_b))
        if len_ratio < 0.5:
            return 0.0

        name_sim = fuzz.token_set_ratio(name_a, name_b) / 100
        scores.append(name_sim)
        weights.append(0.5)

    if a.get("address") and b.get("address"):
        addr_sim = fuzz.token_set_ratio(normalize(a["address"]), normalize(b["address"])) / 100
        scores.append(addr_sim)
        weights.append(0.3)

    if a.get("latitude") and b.get("latitude"):
        try:
            lat_diff = abs(float(a["latitude"]) - float(b["latitude"]))
            lng_diff = abs(float(a["longitude"]) - float(b["longitude"]))
            # ~0.001 degree ~ 100m; treat as same spot if below 0.0005
            coord_sim = max(0, 1 - (lat_diff + lng_diff) / 0.001)
            scores.append(coord_sim)
            weights.append(0.2)
        except (ValueError, TypeError):
            pass

    if not scores:
        return 0.0  # no shared fields -> cannot compare

    # SAFETY GUARD 2: If we ONLY have the name to compare (no address, no coords),
    # we require a much higher threshold to prevent false merges based on common city names.
    if len(scores) == 1:
        return 0.0

    total_weight = sum(weights)
    return sum(s * w for s, w in zip(scores, weights)) / total_weight

def find_clusters(
    records: list[dict], threshold: float = 0.75
) -> tuple[list[list[str]], list[dict]]:
    """Return duplicate clusters and gray-zone pair flags."""
    n = len(records)
    total_possible_pairs = n * (n - 1) / 2
    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x, y):
        parent[find(x)] = find(y)

    pair_flags = []
    # Current blocking strategy: every possible pair is a candidate (no filter yet).
    candidate_pairs = 0
    for i in range(n):
        for j in range(i + 1, n):
            candidate_pairs += 1
            sim = score_pair(records[i], records[j])
            if sim >= threshold:
                union(i, j)
                if sim < 0.9:
                    pair_flags.append({
                        "pair": [records[i]["id"], records[j]["id"]],
                        "similarity": round(sim, 2),
                        "reason": "相似度落在灰色区间。",
                        "reason_en": "Similarity falls in the gray zone.",
                        "suggested_action": "review",
                    })

    reduction_ratio = (
        1 - (candidate_pairs / total_possible_pairs)
        if total_possible_pairs > 0
        else 0.0
    )
    # Make instrumentation visible in standalone runs without overriding app logging.
    if not logging.getLogger().handlers:
        logging.basicConfig(level=logging.INFO, format="%(message)s")
    logger.info("Total possible pairs: %d", int(total_possible_pairs))
    logger.info("Candidate pairs: %d", candidate_pairs)
    logger.info("Blocking reduction ratio: %.2f%%", reduction_ratio * 100)

    clusters = {}
    for i in range(n):
        root = find(i)
        clusters.setdefault(root, []).append(records[i]["id"])

    return [c for c in clusters.values() if len(c) > 1], pair_flags