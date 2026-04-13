import os
from typing import Any, Iterable

import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import linear_kernel

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")
PRODUCTS_FILE = os.path.join(DATA_DIR, "products.csv")


def _coerce_bool(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


class ContentRecommender:
    def __init__(self):
        self.products = pd.DataFrame()
        self.tfidf: Any = None
        self.tfidf_matrix: Any = None
        self.product_index: dict[int, int] = {}
        self.family_by_product: dict[int, str] = {}

    def fit(self):
        if not os.path.exists(PRODUCTS_FILE):
            self.products = pd.DataFrame()
            self.tfidf = None
            self.tfidf_matrix = None
            self.product_index = {}
            self.family_by_product = {}
            return

        self.products = pd.read_csv(PRODUCTS_FILE).fillna("")
        if self.products.empty:
            self.tfidf = None
            self.tfidf_matrix = None
            self.product_index = {}
            self.family_by_product = {}
            return

        for column in ["brand", "subcategory", "variant_label", "description", "product_family_id", "is_default"]:
            if column not in self.products.columns:
                self.products[column] = ""

        product_id_series = pd.Series(pd.to_numeric(self.products["product_id"], errors="coerce"), index=self.products.index)
        self.products["product_id"] = product_id_series.fillna(0).astype(int)
        self.products["product_family_id"] = self.products["product_family_id"].astype(str).str.strip()
        self.products["is_default"] = self.products["is_default"].apply(_coerce_bool)

        # Weight the important browse fields more heavily so family-level similarity
        # stays strong even when variants differ.
        self.products["text"] = (
            self.products["name"].astype(str) + " "
            + self.products["name"].astype(str) + " "
            + self.products["brand"].astype(str) + " "
            + self.products["category"].astype(str) + " "
            + self.products["subcategory"].astype(str) + " "
            + self.products["variant_label"].astype(str) + " "
            + self.products["description"].astype(str) + " "
            + self.products["description"].astype(str)
        ).str.replace(r"\s+", " ", regex=True).str.strip()

        if not self.products["text"].str.len().gt(0).any():
            self.products["text"] = "catalog product"

        self.tfidf = TfidfVectorizer(stop_words="english", ngram_range=(1, 2), max_features=8000)
        self.tfidf_matrix = self.tfidf.fit_transform(self.products["text"])
        self.product_index = {
            int(product_id): int(index)
            for index, product_id in zip(
                self.products.index.tolist(),
                self.products["product_id"].tolist(),
            )
        }
        self.family_by_product = {
            int(product_id): str(family_id)
            for product_id, family_id in zip(
                self.products["product_id"].tolist(),
                self.products["product_family_id"].tolist(),
            )
        }

    def _normalize_ids(self, values: Iterable[Any]) -> set[int]:
        normalized: set[int] = set()
        for value in values:
            try:
                normalized.add(int(value))
            except (TypeError, ValueError):
                continue
        return normalized

    def _row_to_dict(self, row: pd.Series) -> dict[str, Any]:
        return {str(key): value for key, value in row.to_dict().items()}

    def _fallback_rows(
        self,
        limit: int,
        exclude_product_ids: set[int],
        exclude_family_ids: set[str],
        preferred_categories: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        if limit <= 0 or self.products.empty:
            return []

        frame = self.products.sort_values(
            by=["is_default", "product_id"],
            ascending=[False, False],
        )

        if preferred_categories:
            preferred = frame[frame["category"].isin(preferred_categories)]
            remainder = frame[~frame.index.isin(preferred.index)]
            frame = pd.concat([preferred, remainder], ignore_index=True)

        rows: list[dict[str, Any]] = []
        selected_families = set(exclude_family_ids)

        for _, row in frame.iterrows():
            product_id = int(row["product_id"])
            family_id = str(row["product_family_id"])
            if product_id in exclude_product_ids or family_id in selected_families:
                continue
            rows.append(self._row_to_dict(row))
            exclude_product_ids.add(product_id)
            selected_families.add(family_id)
            if len(rows) >= limit:
                break

        return rows

    def recommend_similar(
        self,
        product_id: int,
        top_n: int = 5,
        exclude_product_ids: Iterable[Any] | None = None,
        exclude_family_ids: Iterable[Any] | None = None,
    ) -> list[dict[str, Any]]:
        if self.tfidf_matrix is None or product_id not in self.product_index:
            return []

        excluded_products = self._normalize_ids(exclude_product_ids or [])
        excluded_products.add(int(product_id))

        excluded_families = {str(value) for value in (exclude_family_ids or []) if value}
        excluded_families.add(self.family_by_product.get(int(product_id), ""))

        idx = self.product_index[int(product_id)]
        cosine_similarities = linear_kernel(self.tfidf_matrix[idx : idx + 1], self.tfidf_matrix).flatten()
        related_indices = cosine_similarities.argsort()[::-1]

        recommended: list[dict[str, Any]] = []
        selected_families = set(excluded_families)
        source_category = str(self.products.loc[idx, "category"])

        for related_idx in related_indices:
            row = self.products.loc[related_idx]
            related_product_id = int(row["product_id"])
            family_id = str(row["product_family_id"])

            if related_product_id in excluded_products or family_id in selected_families:
                continue
            if cosine_similarities[related_idx] <= 0:
                continue

            recommended.append(self._row_to_dict(row))
            excluded_products.add(related_product_id)
            selected_families.add(family_id)

            if len(recommended) >= top_n:
                return recommended

        recommended.extend(
            self._fallback_rows(
                top_n - len(recommended),
                excluded_products,
                selected_families,
                preferred_categories=[source_category] if source_category else None,
            )
        )
        return recommended[:top_n]

    def recommend_for_user(
        self,
        user_interactions: pd.DataFrame,
        user_id: int,
        top_n: int = 10,
        exclude_product_ids: Iterable[Any] | None = None,
        exclude_family_ids: Iterable[Any] | None = None,
    ) -> list[dict[str, Any]]:
        if self.tfidf_matrix is None or self.products.empty:
            return []

        user_items = user_interactions[user_interactions["user_id"] == user_id]
        if user_items.empty:
            return []

        excluded_products = self._normalize_ids(exclude_product_ids or [])
        excluded_products.update(self._normalize_ids(user_items["product_id"].tolist()))

        excluded_families = {str(value) for value in (exclude_family_ids or []) if value}
        preferred_categories: list[str] = []
        user_vector = None

        for _, row in user_items.iterrows():
            product_id = int(row["product_id"])
            if product_id not in self.product_index:
                continue

            product_idx = self.product_index[product_id]
            family_id = self.family_by_product.get(product_id, "")
            if family_id:
                excluded_families.add(family_id)

            category = str(self.products.loc[product_idx, "category"]).strip()
            if category and category not in preferred_categories:
                preferred_categories.append(category)

            quantity = max(float(row.get("quantity", 1) or 1), 1.0)
            weighted_vector = self.tfidf_matrix[product_idx] * quantity
            user_vector = weighted_vector if user_vector is None else user_vector + weighted_vector

        if user_vector is None:
            return []

        cosine_similarities = linear_kernel(user_vector, self.tfidf_matrix).flatten()
        related_indices = cosine_similarities.argsort()[::-1]

        recommended: list[dict[str, Any]] = []
        selected_families = set(excluded_families)

        for related_idx in related_indices:
            row = self.products.loc[related_idx]
            related_product_id = int(row["product_id"])
            family_id = str(row["product_family_id"])

            if related_product_id in excluded_products or family_id in selected_families:
                continue
            if cosine_similarities[related_idx] <= 0:
                continue

            recommended.append(self._row_to_dict(row))
            excluded_products.add(related_product_id)
            selected_families.add(family_id)

            if len(recommended) >= top_n:
                return recommended

        recommended.extend(
            self._fallback_rows(
                top_n - len(recommended),
                excluded_products,
                selected_families,
                preferred_categories=preferred_categories,
            )
        )
        return recommended[:top_n]
