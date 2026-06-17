"""
Neo4j 5.x migration + structural downsampling script.

Phase 1 (mandatory pre-calculation)
-----------------------------------
Source metrics:
- Total nodes: 237,358
- Total relationships: 389,982
- Articles: 65,578
- Chunks: 108,112
- Other nodes: 237,358 - 65,578 - 108,112 = 63,668

Target safety envelope (50% of Aura Free hard caps):
- Node ceiling: 100,000
- Relationship ceiling: 200,000
- Disk safety budget: 1 GB

Derived structural ratios from source:
- Chunk/article ratio = 108,112 / 65,578 = 1.6483 (~1.648)
- Other/article ratio = 63,668 / 65,578 = 0.9709

Node-budget equation to avoid cutting off connected entity classes:
Let A = migrated articles, C = migrated chunks, O = migrated other entities.
Use source-preserving ratios:
  C = 1.6483A
  O = 0.9709A
Total nodes N = A + C + O = 3.6192A <= 100,000
=> A <= floor(100,000 / 3.6192) = 27,630

Storage sanity equation (vector regeneration considered):
- Native text/metadata per article ecosystem: ~7.6 KB
- New vector footprint: 3 KB per chunk
- Per-article storage = 7.6 + (1.6483 * 3) = 12.545 KB
- 1 GB budget gives theoretical A <= 1,048,576 / 12.545 = 83,584

Storage is NOT the binding constraint; node budget is.

Final hard cap used by this script:
- MAX_ARTICLES = 27,630
- MAX_CHUNKS = floor(27,630 * 1.6483) = 45,538
- MAX_TOTAL_NODES = 100,000
- MAX_TOTAL_RELATIONSHIPS = 200,000
"""

from __future__ import annotations

import math
import os
import random
import sys
from collections import Counter, deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence, Set, Tuple

from dotenv import load_dotenv
from neo4j import GraphDatabase
from neo4j.exceptions import Neo4jError

# Load credentials from migration_tools/.env (same directory as this file)
_ENV_PATH = Path(__file__).parent / ".env"
load_dotenv(dotenv_path=_ENV_PATH, override=True)


# -----------------------------------------------------------------------------
# Credentials — set these in migration_tools/.env, never hard-code here
# -----------------------------------------------------------------------------
SOURCE_URI = os.environ["SOURCE_NEO4J_URI"]
SOURCE_USER = os.environ["SOURCE_NEO4J_USER"]
SOURCE_PASSWORD = os.environ["SOURCE_NEO4J_PASSWORD"]

TARGET_URI = os.environ["TARGET_NEO4J_URI"]
TARGET_USER = os.environ["TARGET_NEO4J_USER"]
TARGET_PASSWORD = os.environ["TARGET_NEO4J_PASSWORD"]


# -----------------------------------------------------------------------------
# Safety and migration ceilings
# -----------------------------------------------------------------------------
MAX_TOTAL_NODES = 100_000
MAX_TOTAL_RELATIONSHIPS = 200_000
DISK_SAFETY_BUDGET_GB = 1.0

CHUNK_TO_ARTICLE_RATIO = 108_112 / 65_578
OTHER_TO_ARTICLE_RATIO = (237_358 - 65_578 - 108_112) / 65_578

MAX_ARTICLES = math.floor(MAX_TOTAL_NODES / (1 + CHUNK_TO_ARTICLE_RATIO + OTHER_TO_ARTICLE_RATIO))
MAX_CHUNKS = math.floor(MAX_ARTICLES * CHUNK_TO_ARTICLE_RATIO)

LEGACY_VECTOR_KEYS = {
    "embedding",
    "embedding_google",
    "embedding_google_004",
    "embedding_sbert",
}


# -----------------------------------------------------------------------------
# Extraction and write tuning
# -----------------------------------------------------------------------------
BATCH_SIZE = 2_000
ARTICLE_SEED_TARGET = 12_000
ORG_SEED_TARGET = 2_500
TOP_SITES_FOR_BALANCE = 24
EXPANSION_ANCHOR_BATCH = 120
EXPANSION_RESULT_CAP = 15_000


@dataclass
class NodeRecord:
    nid: int
    labels: Tuple[str, ...]
    props: Dict[str, Any]


@dataclass
class RelationshipRecord:
    rid: int
    sid: int
    tid: int
    rtype: str
    props: Dict[str, Any]


def chunks(seq: Sequence[int], size: int) -> Iterable[List[int]]:
    for i in range(0, len(seq), size):
        yield list(seq[i : i + size])


def sanitize_properties(props: Dict[str, Any]) -> Dict[str, Any]:
    cleaned = {k: v for k, v in props.items() if k not in LEGACY_VECTOR_KEYS}
    cleaned.pop("_src_id", None)
    return cleaned


def escape_label_or_type(name: str) -> str:
    return "`" + name.replace("`", "``") + "`"


def print_phase_1_summary() -> None:
    per_article_kb = 7.6 + (CHUNK_TO_ARTICLE_RATIO * 3.0)
    storage_article_bound = math.floor((DISK_SAFETY_BUDGET_GB * 1024 * 1024) / per_article_kb)
    rel_per_article = 389_982 / 65_578
    relationship_article_bound = math.floor(MAX_TOTAL_RELATIONSHIPS / rel_per_article)

    print("=== Phase 1: Pre-Calculation Summary ===")
    print(f"Safety node cap: {MAX_TOTAL_NODES:,}")
    print(f"Safety relationship cap: {MAX_TOTAL_RELATIONSHIPS:,}")
    print(f"Derived chunk/article ratio: {CHUNK_TO_ARTICLE_RATIO:.4f}")
    print(f"Derived other/article ratio: {OTHER_TO_ARTICLE_RATIO:.4f}")
    print(f"Computed hard article cap (node-bound): {MAX_ARTICLES:,}")
    print(f"Computed chunk cap from ratio: {MAX_CHUNKS:,}")
    print(f"Article cap if storage-bound at 1 GB: {storage_article_bound:,}")
    print(f"Article cap if relationship-bound at 200k: {relationship_article_bound:,}")
    print("Binding constraint: node cap (100,000).")
    print("========================================")


def create_target_constraints(target_driver) -> None:
    queries = [
        "CREATE CONSTRAINT migrated_src_id IF NOT EXISTS FOR (n:Migrated) REQUIRE n._src_id IS UNIQUE",
        "CREATE CONSTRAINT article_id_unique IF NOT EXISTS FOR (n:Article) REQUIRE n.id IS UNIQUE",
        "CREATE CONSTRAINT chunk_id_unique IF NOT EXISTS FOR (n:Chunk) REQUIRE n.id IS UNIQUE",
        "CREATE CONSTRAINT org_name_unique IF NOT EXISTS FOR (n:Organization) REQUIRE n.name IS UNIQUE",
        "CREATE CONSTRAINT person_name_unique IF NOT EXISTS FOR (n:Person) REQUIRE n.name IS UNIQUE",
        "CREATE CONSTRAINT city_name_unique IF NOT EXISTS FOR (n:City) REQUIRE n.name IS UNIQUE",
        "CREATE CONSTRAINT country_name_unique IF NOT EXISTS FOR (n:Country) REQUIRE n.name IS UNIQUE",
        "CREATE CONSTRAINT industry_name_unique IF NOT EXISTS FOR (n:IndustryCategory) REQUIRE n.name IS UNIQUE",
    ]
    with target_driver.session() as session:
        for q in queries:
            try:
                session.run(q).consume()
                print(f"Constraint OK: {q}")
            except Neo4jError as exc:
                print(f"Constraint warning (continuing): {exc}")


def fetch_top_sites(source_driver, limit_sites: int) -> List[str]:
    q = """
    MATCH (a:Article)
    WITH coalesce(a.siteName, '__unknown__') AS site, count(*) AS cnt
    ORDER BY cnt DESC
    LIMIT $limit_sites
    RETURN collect(site) AS sites
    """
    with source_driver.session() as session:
        rec = session.run(q, limit_sites=limit_sites).single()
    return list(rec["sites"]) if rec and rec["sites"] else ["__unknown__"]


def fetch_balanced_article_seeds(source_driver, article_seed_target: int) -> List[int]:
    sites = fetch_top_sites(source_driver, TOP_SITES_FOR_BALANCE)
    per_bucket_per_site = max(4, article_seed_target // max(1, len(sites) * 3))

    seeded: Set[int] = set()
    with source_driver.session() as session:
        for site in sites:
            for bucket in ("positive", "neutral", "negative"):
                q = """
                MATCH (a:Article)
                WHERE coalesce(a.siteName, '__unknown__') = $site
                  AND (
                    ($bucket = 'positive' AND coalesce(a.sentiment, 0.0) >= 0.25) OR
                    ($bucket = 'neutral'  AND coalesce(a.sentiment, 0.0) > -0.25 AND coalesce(a.sentiment, 0.0) < 0.25) OR
                    ($bucket = 'negative' AND coalesce(a.sentiment, 0.0) <= -0.25)
                  )
                WITH a
                ORDER BY
                    CASE
                        WHEN $bucket = 'positive' THEN coalesce(a.sentiment, 0.0)
                        WHEN $bucket = 'negative' THEN -coalesce(a.sentiment, 0.0)
                        ELSE abs(coalesce(a.sentiment, 0.0))
                    END DESC,
                    id(a)
                LIMIT $lim
                RETURN collect(id(a)) AS ids
                """
                rec = session.run(q, site=site, bucket=bucket, lim=per_bucket_per_site).single()
                if rec and rec["ids"]:
                    seeded.update(rec["ids"])

        if len(seeded) < article_seed_target:
            deficit = article_seed_target - len(seeded)
            q_fill = """
            MATCH (a:Article)
            WHERE NOT id(a) IN $exclude
            WITH a
            ORDER BY rand()
            LIMIT $lim
            RETURN collect(id(a)) AS ids
            """
            rec = session.run(q_fill, exclude=list(seeded), lim=deficit).single()
            if rec and rec["ids"]:
                seeded.update(rec["ids"])

    seeded_list = list(seeded)
    random.shuffle(seeded_list)
    return seeded_list[:article_seed_target]


def fetch_organization_seeds(source_driver, org_seed_target: int) -> List[int]:
    q = """
    MATCH (o:Organization)
    WITH o, COUNT { (o)--() } AS degree
    ORDER BY degree DESC, id(o)
    LIMIT $lim
    RETURN collect(id(o)) AS ids
    """
    with source_driver.session() as session:
        rec = session.run(q, lim=org_seed_target).single()
    ids = list(rec["ids"]) if rec and rec["ids"] else []
    random.shuffle(ids)
    return ids


def node_labels_lookup(source_driver, node_ids: Sequence[int]) -> Dict[int, Tuple[str, ...]]:
    out: Dict[int, Tuple[str, ...]] = {}
    q = """
    MATCH (n)
    WHERE id(n) IN $ids
    RETURN id(n) AS nid, labels(n) AS labels
    """
    with source_driver.session() as session:
        for batch in chunks(list(node_ids), BATCH_SIZE):
            for rec in session.run(q, ids=batch):
                out[rec["nid"]] = tuple(rec["labels"])
    return out


def grow_cluster_nodes(
    source_driver,
    article_seed_ids: Sequence[int],
    org_seed_ids: Sequence[int],
) -> Set[int]:
    selected: Set[int] = set()
    frontier: deque[int] = deque()
    processed_anchors: Set[int] = set()

    article_count = 0
    chunk_count = 0

    seed_ids = list(dict.fromkeys(list(article_seed_ids) + list(org_seed_ids)))
    seed_labels = node_labels_lookup(source_driver, seed_ids)

    for nid in seed_ids:
        labels = seed_labels.get(nid, tuple())
        is_article = "Article" in labels
        is_chunk = "Chunk" in labels

        if is_article and article_count >= MAX_ARTICLES:
            continue
        if is_chunk and chunk_count >= MAX_CHUNKS:
            continue
        if len(selected) >= MAX_TOTAL_NODES:
            break

        selected.add(nid)
        frontier.append(nid)
        if is_article:
            article_count += 1
        if is_chunk:
            chunk_count += 1

    print(f"Seeded nodes: {len(selected):,} (articles: {article_count:,}, chunks: {chunk_count:,})")

    with source_driver.session() as session:
        while frontier and len(selected) < MAX_TOTAL_NODES:
            anchor_batch: List[int] = []
            while frontier and len(anchor_batch) < EXPANSION_ANCHOR_BATCH:
                aid = frontier.popleft()
                if aid in processed_anchors:
                    continue
                processed_anchors.add(aid)
                anchor_batch.append(aid)

            if not anchor_batch:
                continue

            q = """
            MATCH (src)
            WHERE id(src) IN $anchor_ids
            MATCH p = (src)-[*1..3]-(tgt)
            UNWIND nodes(p) AS n
            WITH DISTINCT n
            RETURN id(n) AS nid, labels(n) AS labels
            LIMIT $lim
            """
            candidates = session.run(q, anchor_ids=anchor_batch, lim=EXPANSION_RESULT_CAP)

            added_this_round = 0
            for rec in candidates:
                nid = rec["nid"]
                if nid in selected:
                    continue
                labels = rec["labels"]
                is_article = "Article" in labels
                is_chunk = "Chunk" in labels

                if is_article and article_count >= MAX_ARTICLES:
                    continue
                if is_chunk and chunk_count >= MAX_CHUNKS:
                    continue
                if len(selected) >= MAX_TOTAL_NODES:
                    break

                selected.add(nid)
                frontier.append(nid)
                added_this_round += 1
                if is_article:
                    article_count += 1
                if is_chunk:
                    chunk_count += 1

            print(
                "Expanded with "
                f"{len(anchor_batch):,} anchors; +{added_this_round:,} nodes; "
                f"total={len(selected):,}, articles={article_count:,}, chunks={chunk_count:,}"
            )

            if len(selected) >= MAX_TOTAL_NODES:
                break

    return selected


def fetch_nodes(source_driver, node_ids: Sequence[int]) -> List[NodeRecord]:
    out: List[NodeRecord] = []
    q = """
    MATCH (n)
    WHERE id(n) IN $ids
    RETURN id(n) AS nid, labels(n) AS labels, properties(n) AS props
    """
    with source_driver.session() as session:
        for batch in chunks(list(node_ids), BATCH_SIZE):
            for rec in session.run(q, ids=batch):
                out.append(
                    NodeRecord(
                        nid=rec["nid"],
                        labels=tuple(rec["labels"]),
                        props=sanitize_properties(dict(rec["props"])),
                    )
                )
    return out


def fetch_relationships(source_driver, valid_nodes: Set[int]) -> List[RelationshipRecord]:
    out: List[RelationshipRecord] = []
    valid_list = list(valid_nodes)
    valid_set = set(valid_nodes)

    q = """
    MATCH (s)-[r]->(t)
    WHERE id(s) IN $source_ids
    RETURN id(r) AS rid, id(s) AS sid, id(t) AS tid, type(r) AS rtype, properties(r) AS props
    """

    with source_driver.session() as session:
        for batch in chunks(valid_list, BATCH_SIZE):
            for rec in session.run(q, source_ids=batch):
                sid = rec["sid"]
                tid = rec["tid"]
                if sid in valid_set and tid in valid_set:
                    out.append(
                        RelationshipRecord(
                            rid=rec["rid"],
                            sid=sid,
                            tid=tid,
                            rtype=rec["rtype"],
                            props=sanitize_properties(dict(rec["props"])),
                        )
                    )

    if len(out) > MAX_TOTAL_RELATIONSHIPS:
        out = out[:MAX_TOTAL_RELATIONSHIPS]
    return out


def upsert_nodes(target_driver, nodes: List[NodeRecord]) -> None:
    grouped: Dict[Tuple[str, ...], List[Dict[str, Any]]] = {}
    for n in nodes:
        labels = tuple(sorted(set(n.labels) | {"Migrated"}))
        grouped.setdefault(labels, []).append({"nid": n.nid, "props": n.props})

    with target_driver.session() as session:
        for labels, rows in grouped.items():
            label_str = ":".join(escape_label_or_type(lb) for lb in labels)
            q = f"""
            UNWIND $rows AS row
            MERGE (n:{label_str} {{_src_id: row.nid}})
            SET n += row.props
            """
            for batch in chunks(rows, BATCH_SIZE):  # type: ignore[arg-type]
                session.execute_write(lambda tx, data: tx.run(q, rows=data).consume(), batch)


def upsert_relationships(target_driver, rels: List[RelationshipRecord]) -> None:
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for r in rels:
        grouped.setdefault(r.rtype, []).append(
            {
                "rid": r.rid,
                "sid": r.sid,
                "tid": r.tid,
                "props": r.props,
            }
        )

    with target_driver.session() as session:
        for rtype, rows in grouped.items():
            escaped_rtype = escape_label_or_type(rtype)
            q = f"""
            UNWIND $rows AS row
            MATCH (s:Migrated {{_src_id: row.sid}})
            MATCH (t:Migrated {{_src_id: row.tid}})
            MERGE (s)-[r:{escaped_rtype} {{_src_rid: row.rid}}]->(t)
            SET r += row.props
            """
            for batch in chunks(rows, BATCH_SIZE):  # type: ignore[arg-type]
                session.execute_write(lambda tx, data: tx.run(q, rows=data).consume(), batch)


def summarize_labels(nodes: List[NodeRecord]) -> str:
    c = Counter()
    for n in nodes:
        if n.labels:
            for lb in n.labels:
                c[lb] += 1
        else:
            c["__NO_LABEL__"] += 1
    parts = [f"{k}:{v}" for k, v in c.most_common()]
    return ", ".join(parts)


def main() -> int:
    random.seed(42)
    print_phase_1_summary()

    source_driver = GraphDatabase.driver(SOURCE_URI, auth=(SOURCE_USER, SOURCE_PASSWORD))
    target_driver = GraphDatabase.driver(TARGET_URI, auth=(TARGET_USER, TARGET_PASSWORD))

    try:
        print("Creating target constraints before inserts...")
        create_target_constraints(target_driver)

        print("Selecting balanced article seeds by sentiment/siteName...")
        article_seed_ids = fetch_balanced_article_seeds(source_driver, ARTICLE_SEED_TARGET)
        print(f"Article seeds selected: {len(article_seed_ids):,}")

        print("Selecting organization seeds by degree...")
        org_seed_ids = fetch_organization_seeds(source_driver, ORG_SEED_TARGET)
        print(f"Organization seeds selected: {len(org_seed_ids):,}")

        print("Running 3-hop anchor expansion with hard node caps...")
        selected_node_ids = grow_cluster_nodes(source_driver, article_seed_ids, org_seed_ids)
        print(f"Selected unique nodes: {len(selected_node_ids):,}")

        print("Extracting node payloads...")
        nodes = fetch_nodes(source_driver, list(selected_node_ids))
        print(f"Fetched nodes: {len(nodes):,}")
        print(f"Node label distribution: {summarize_labels(nodes)}")

        print("Extracting relationships constrained to selected node set...")
        rels = fetch_relationships(source_driver, selected_node_ids)
        print(f"Fetched valid relationships: {len(rels):,}")

        print("Writing nodes to target in 2,000-record batches...")
        upsert_nodes(target_driver, nodes)
        print("Node write complete.")

        print("Writing relationships to target in 2,000-record batches...")
        upsert_relationships(target_driver, rels)
        print("Relationship write complete.")

        print("Migration + prune completed successfully.")
        print(f"Final migrated nodes: {len(nodes):,} (cap {MAX_TOTAL_NODES:,})")
        print(f"Final migrated relationships: {len(rels):,} (cap {MAX_TOTAL_RELATIONSHIPS:,})")
        return 0

    except Exception as exc:  # noqa: BLE001
        print(f"Migration failed: {exc}")
        return 1
    finally:
        source_driver.close()
        target_driver.close()


if __name__ == "__main__":
    sys.exit(main())
