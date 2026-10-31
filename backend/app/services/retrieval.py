"""Build passage search and keep source metadata tied to a live resource."""
PASSAGE_INDEX = "BuddysBrainPassagesIndex"
MAX_CONTEXT_PASSAGES = 8
MAX_PASSAGES_PER_RESOURCE = 3


def passage_pipeline(vector):
    return [
        {"$vectorSearch": {"index": PASSAGE_INDEX, "path": "embedding", "queryVector": vector,
                           "numCandidates": 600, "limit": 30}},
        {"$project": {"resource_id": 1, "revision": 1, "ordinal": 1, "page": 1,
                      "text": 1, "score": {"$meta": "vectorSearchScore"}}},
        {"$lookup": {
            "from": "resources", "let": {"resource_id": "$resource_id", "revision": "$revision"},
            "pipeline": [
                {"$match": {"$expr": {"$and": [
                    {"$eq": ["$_id", "$$resource_id"]},
                    {"$eq": ["$passage_revision", "$$revision"]},
                ]}}},
                {"$project": {"title": 1, "summary": 1, "course": 1,
                              "media_type": 1, "media_link": 1}},
            ], "as": "resource",
        }},
        # Exclude deleted parents and unfinished/stale passage revisions.
        {"$unwind": "$resource"},
        {"$sort": {"score": -1}},
    ]


def group_passages(rows):
    groups = {}
    count = 0
    for row in rows:
        parent = row["resource"]
        resource_id = str(parent["_id"])
        if resource_id not in groups:
            if len(groups) == 5:
                continue
            groups[resource_id] = {**parent, "_id": resource_id, "score": row["score"],
                                   "evidence_type": "passages", "passages": []}
        excerpts = groups[resource_id]["passages"]
        if len(excerpts) >= MAX_PASSAGES_PER_RESOURCE:
            continue
        count += 1
        excerpts.append({"citation": f"P{count}", "text": row["text"],
                         "page": row.get("page"), "ordinal": row["ordinal"]})
        if count == MAX_CONTEXT_PASSAGES:
            break
    return list(groups.values())


def combine_evidence(passages, summaries):
    # Prefer original excerpts, and never pass the same resource's generated
    # summary as if it were additional independent evidence.
    combined = list(passages)
    used = {r["_id"] for r in combined}
    for resource in summaries:
        if str(resource["_id"]) not in used and len(combined) < 5:
            combined.append(resource)
            used.add(str(resource["_id"]))
    return combined
