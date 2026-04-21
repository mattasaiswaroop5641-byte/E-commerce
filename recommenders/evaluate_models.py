import argparse
import os
import tempfile
import warnings
from dataclasses import dataclass
from typing import Any, cast

import pandas as pd
from sklearn.exceptions import ConvergenceWarning

from collab import CollabRecommender
from content_based import ContentRecommender
import collab as collab_module


DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")
PRODUCTS_FILE = os.path.join(DATA_DIR, "products.csv")
INTERACTIONS_FILE = os.path.join(DATA_DIR, "interactions.csv")


@dataclass
class EvalResult:
    name: str
    users: int
    users_with_recs: int
    k: int
    hit_rate_at_k: float
    precision_at_k: float
    recall_at_k: float
    mrr_at_k: float
    family_hit_rate_at_k: float


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def load_data() -> tuple[pd.DataFrame, pd.DataFrame, dict[int, str]]:
    if not os.path.exists(PRODUCTS_FILE):
        raise FileNotFoundError(f"Missing products file: {PRODUCTS_FILE}")
    if not os.path.exists(INTERACTIONS_FILE):
        raise FileNotFoundError(f"Missing interactions file: {INTERACTIONS_FILE}")

    # NOTE: Keep intermediate variables typed as DataFrames/Series to help static
    # analyzers (e.g., Pylance) choose the correct pandas overloads.
    products: pd.DataFrame = pd.read_csv(PRODUCTS_FILE)
    products = products.fillna("")
    interactions: pd.DataFrame = pd.read_csv(INTERACTIONS_FILE)
    interactions = interactions.fillna("")

    if products.empty or interactions.empty:
        raise ValueError("Products or interactions file is empty.")

    products_product_id = pd.to_numeric(cast(pd.Series, products["product_id"]), errors="coerce")
    products["product_id"] = products_product_id.fillna(0).astype("int64")
    if "product_family_id" not in products.columns:
        products["product_family_id"] = products["product_id"].astype(str)
    products["product_family_id"] = products["product_family_id"].astype(str).str.strip()

    interactions_user_id = pd.to_numeric(cast(pd.Series, interactions["user_id"]), errors="coerce")
    interactions["user_id"] = interactions_user_id.fillna(0).astype("int64")
    interactions_product_id = pd.to_numeric(cast(pd.Series, interactions["product_id"]), errors="coerce")
    interactions["product_id"] = interactions_product_id.fillna(0).astype("int64")
    interactions_quantity = pd.to_numeric(cast(pd.Series, interactions["quantity"]), errors="coerce")
    interactions["quantity"] = interactions_quantity.fillna(0.0).astype(float)
    interactions = interactions[interactions["quantity"] > 0].copy()
    interactions = interactions[interactions["product_id"].isin(products["product_id"])].copy()
    if interactions.empty:
        raise ValueError("No valid interactions after cleaning.")

    if "timestamp" in interactions.columns:
        interactions["timestamp"] = pd.to_datetime(interactions["timestamp"], errors="coerce")
    else:
        interactions["timestamp"] = pd.NaT
    interactions["timestamp"] = interactions["timestamp"].fillna(pd.Timestamp("1970-01-01"))
    interactions = interactions.reset_index(drop=True)

    family_by_product = {
        int(product_id): str(family_id)
        for product_id, family_id in zip(
            products["product_id"].tolist(),
            products["product_family_id"].tolist(),
        )
    }

    return products, interactions, family_by_product


def build_leave_one_out_split(
    interactions: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[int, int]]:
    rows: pd.DataFrame = interactions.sort_values(["user_id", "timestamp"]).copy()
    heldout_rows: list[int] = []
    heldout_product_by_user: dict[int, int] = {}

    for user_id, group in rows.groupby("user_id"):
        if len(group) < 2:
            continue
        heldout_row_index = int(_safe_float(group.index[-1]))
        heldout_rows.append(heldout_row_index)
        heldout_product_by_user[int(_safe_float(user_id))] = int(_safe_float(group.iloc[-1]["product_id"]))

    if not heldout_rows:
        raise ValueError("Not enough users with at least 2 interactions for leave-one-out evaluation.")

    train: pd.DataFrame = rows.drop(index=heldout_rows).copy()
    train = train[["user_id", "product_id", "quantity", "timestamp"]]

    return train, heldout_product_by_user


def build_user_seen(train: pd.DataFrame) -> dict[int, set[int]]:
    seen: dict[int, set[int]] = {}
    for user_id, group in train.groupby("user_id"):
        seen[int(_safe_float(user_id))] = set(int(_safe_float(product_id)) for product_id in group["product_id"].tolist())
    return seen


def _compute_metrics(
    name: str,
    k: int,
    predictions: dict[int, list[int]],
    heldout_product_by_user: dict[int, int],
    family_by_product: dict[int, str],
) -> EvalResult:
    users = sorted(heldout_product_by_user.keys())
    total_users = len(users)
    if total_users == 0:
        raise ValueError("No users to evaluate.")

    hits = 0
    reciprocal_sum = 0.0
    family_hits = 0
    users_with_recs = 0

    for user_id in users:
        actual_product = int(heldout_product_by_user[user_id])
        actual_family = family_by_product.get(actual_product, "")
        recs = predictions.get(user_id, [])[:k]
        if recs:
            users_with_recs += 1

        if actual_product in recs:
            hits += 1
            rank = recs.index(actual_product) + 1
            reciprocal_sum += 1.0 / rank

        if actual_family:
            rec_families = {family_by_product.get(int(product_id), "") for product_id in recs}
            if actual_family in rec_families:
                family_hits += 1

    hit_rate = hits / total_users
    precision = hits / (total_users * k) if k > 0 else 0.0
    recall = hit_rate
    mrr = reciprocal_sum / total_users
    family_hit_rate = family_hits / total_users

    return EvalResult(
        name=name,
        users=total_users,
        users_with_recs=users_with_recs,
        k=k,
        hit_rate_at_k=hit_rate,
        precision_at_k=precision,
        recall_at_k=recall,
        mrr_at_k=mrr,
        family_hit_rate_at_k=family_hit_rate,
    )


def evaluate_popularity(
    train: pd.DataFrame,
    heldout_product_by_user: dict[int, int],
    family_by_product: dict[int, str],
    k: int,
) -> EvalResult:
    popularity_ranked = (
        train.groupby("product_id")["quantity"]
        .sum()
        .sort_values(ascending=False)
        .index.astype(int)
        .tolist()
    )

    user_seen = build_user_seen(train)
    predictions: dict[int, list[int]] = {}
    for user_id in heldout_product_by_user:
        seen = user_seen.get(int(user_id), set())
        recs: list[int] = []
        for product_id in popularity_ranked:
            if product_id in seen:
                continue
            recs.append(int(product_id))
            if len(recs) >= k:
                break
        predictions[int(user_id)] = recs

    return _compute_metrics("Popularity baseline", k, predictions, heldout_product_by_user, family_by_product)


def evaluate_collab(
    train: pd.DataFrame,
    heldout_product_by_user: dict[int, int],
    family_by_product: dict[int, str],
    k: int,
) -> EvalResult:
    with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, encoding="utf-8") as temp:
        train_csv = temp.name
    try:
        train.to_csv(train_csv, index=False)
        original_interactions = collab_module.INTERACTIONS_FILE
        original_products = collab_module.PRODUCTS_FILE
        collab_module.INTERACTIONS_FILE = train_csv
        collab_module.PRODUCTS_FILE = PRODUCTS_FILE
        try:
            model = CollabRecommender(n_components=10, random_state=42)
            model.fit()
            predictions: dict[int, list[int]] = {}
            for user_id in heldout_product_by_user:
                recs = model.recommend_for_user(int(user_id), top_n=k)
                rec_ids: list[int] = []
                for row in recs:
                    product_id = int(_safe_float(row.get("product_id"), 0))
                    if product_id > 0:
                        rec_ids.append(product_id)
                predictions[int(user_id)] = rec_ids[:k]
        finally:
            collab_module.INTERACTIONS_FILE = original_interactions
            collab_module.PRODUCTS_FILE = original_products
    finally:
        if os.path.exists(train_csv):
            os.remove(train_csv)

    return _compute_metrics("Collaborative filtering (NMF)", k, predictions, heldout_product_by_user, family_by_product)


def evaluate_content(
    train: pd.DataFrame,
    heldout_product_by_user: dict[int, int],
    family_by_product: dict[int, str],
    k: int,
) -> EvalResult:
    model = ContentRecommender()
    model.fit()

    predictions: dict[int, list[int]] = {}
    for user_id in heldout_product_by_user:
        user_train = train[train["user_id"] == int(user_id)][["user_id", "product_id", "quantity"]]
        recs = model.recommend_for_user(user_train, int(user_id), top_n=k)
        rec_ids: list[int] = []
        for row in recs:
            product_id = int(_safe_float(row.get("product_id"), 0))
            if product_id > 0:
                rec_ids.append(product_id)
        predictions[int(user_id)] = rec_ids[:k]

    return _compute_metrics("Content-based (TF-IDF)", k, predictions, heldout_product_by_user, family_by_product)


def format_result(result: EvalResult) -> str:
    return (
        f"{result.name:<34} "
        f"users={result.users:>4} "
        f"coverage={result.users_with_recs / result.users:>6.2%} "
        f"HitRate@{result.k}={result.hit_rate_at_k:>6.2%} "
        f"Precision@{result.k}={result.precision_at_k:>6.2%} "
        f"MRR@{result.k}={result.mrr_at_k:>6.2%} "
        f"FamilyHit@{result.k}={result.family_hit_rate_at_k:>6.2%}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate recommendation accuracy on leave-one-out split.")
    parser.add_argument("--k", type=int, default=10, help="Top-K cutoff (default: 10)")
    args = parser.parse_args()

    k = max(1, int(args.k))
    warnings.filterwarnings("ignore", category=ConvergenceWarning)

    _, interactions, family_by_product = load_data()
    train, heldout_product_by_user = build_leave_one_out_split(interactions)

    popularity = evaluate_popularity(train, heldout_product_by_user, family_by_product, k)
    collab = evaluate_collab(train, heldout_product_by_user, family_by_product, k)
    content = evaluate_content(train, heldout_product_by_user, family_by_product, k)

    print(f"Evaluation users: {len(heldout_product_by_user)} (leave-one-out)")
    print(format_result(popularity))
    print(format_result(collab))
    print(format_result(content))


if __name__ == "__main__":
    main()
