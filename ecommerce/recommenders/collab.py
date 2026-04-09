import os
from typing import Any, Iterable

import numpy as np
import pandas as pd
from sklearn.decomposition import NMF
from sklearn.preprocessing import normalize

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")
PRODUCTS_FILE = os.path.join(DATA_DIR, "products.csv")
INTERACTIONS_FILE = os.path.join(DATA_DIR, "interactions.csv")


class CollabRecommender:
    def __init__(self, n_components: int = 20, random_state: int = 42):
        self.n_components = n_components
        self.random_state = random_state
        self.model = None
        self.products = pd.DataFrame()
        self.user_ids: list[int] = []
        self.product_ids: list[int] = []
        self.user_index: dict[int, int] = {}
        self.product_index: dict[int, int] = {}
        self.user_seen: dict[int, set[int]] = {}
        self.family_by_product: dict[int, str] = {}
        self.popular_product_ids: list[int] = []
        self.user_factors: np.ndarray | None = None
        self.item_factors: np.ndarray | None = None

    def fit(self):
        if not os.path.exists(PRODUCTS_FILE):
            self.products = pd.DataFrame()
            self.model = None
            return

        self.products = pd.read_csv(PRODUCTS_FILE).fillna("")
        if self.products.empty:
            self.model = None
            return

        self.products["product_id"] = pd.to_numeric(self.products["product_id"], errors="coerce").fillna(0).astype(int)
        if "product_family_id" not in self.products.columns:
            self.products["product_family_id"] = self.products["product_id"].astype(str)
        self.products["product_family_id"] = self.products["product_family_id"].astype(str).str.strip()
        self.products = self.products.drop_duplicates(subset=["product_id"]).reset_index(drop=True)
        self.family_by_product = {
            int(product_id): str(family_id)
            for product_id, family_id in zip(
                self.products["product_id"].tolist(),
                self.products["product_family_id"].tolist(),
            )
        }

        if not os.path.exists(INTERACTIONS_FILE):
            self._prepare_popularity(pd.DataFrame())
            self.model = None
            return

        interactions = pd.read_csv(INTERACTIONS_FILE).fillna("")
        if interactions.empty:
            self._prepare_popularity(interactions)
            self.model = None
            return

        interactions["user_id"] = pd.to_numeric(interactions["user_id"], errors="coerce").fillna(0).astype(int)
        interactions["product_id"] = pd.to_numeric(interactions["product_id"], errors="coerce").fillna(0).astype(int)
        interactions["quantity"] = pd.to_numeric(interactions["quantity"], errors="coerce").fillna(0).astype(float)
        interactions = interactions[interactions["quantity"] > 0]
        interactions = interactions[interactions["product_id"].isin(self.products["product_id"])]

        self._prepare_popularity(interactions)
        if interactions.empty:
            self.model = None
            return

        pivot = interactions.pivot_table(
            index="user_id",
            columns="product_id",
            values="quantity",
            aggfunc="sum",
            fill_value=0.0,
        )
        self.user_ids = [int(user_id) for user_id in pivot.index.to_list()]
        self.product_ids = [int(product_id) for product_id in pivot.columns.to_list()]
        self.user_index = {user_id: idx for idx, user_id in enumerate(self.user_ids)}
        self.product_index = {product_id: idx for idx, product_id in enumerate(self.product_ids)}
        self.user_seen = {}
        for user_id, row in pivot.iterrows():
            seen_products: set[int] = set()
            for product_id, value in row.items():
                try:
                    product_id_int = int(product_id)
                    value_float = float(value)
                except (TypeError, ValueError):
                    continue
                if value_float > 0:
                    seen_products.add(product_id_int)
            self.user_seen[int(user_id)] = seen_products

        matrix = pivot.values
        if matrix.shape[0] < 2 or matrix.shape[1] < 2:
            self.model = None
            return

        max_components = max(1, min(self.n_components, matrix.shape[0] - 1, matrix.shape[1] - 1))
        if max_components < 1:
            self.model = None
            return

        try:
            nmf = NMF(
                n_components=max_components,
                init="nndsvda",
                random_state=self.random_state,
                max_iter=200,
            )
            user_matrix = nmf.fit_transform(matrix)
            item_matrix = nmf.components_
        except Exception:
            self.model = None
            return

        self.model = {"W": user_matrix, "H": item_matrix}
        self.user_factors = normalize(user_matrix, axis=1)
        self.item_factors = normalize(item_matrix.T, axis=1)

    def _prepare_popularity(self, interactions: pd.DataFrame):
        ranked_ids: list[int] = []
        if not interactions.empty:
            popularity = [
                int(product_id)
                for product_id in (
                interactions.groupby("product_id")["quantity"]
                .sum()
                .sort_values(ascending=False)
                .index.astype(int)
                .tolist()
            )
            ]
            ranked_ids.extend(popularity)

        for product_id in self.products["product_id"].astype(int).tolist():
            if product_id not in ranked_ids:
                ranked_ids.append(product_id)
        self.popular_product_ids = ranked_ids

    def _row_to_dict(self, row: pd.Series) -> dict[str, Any]:
        return {str(key): value for key, value in row.to_dict().items()}

    def _normalize_ids(self, values: Iterable[Any]) -> set[int]:
        normalized: set[int] = set()
        for value in values:
            try:
                normalized.add(int(value))
            except (TypeError, ValueError):
                continue
        return normalized

    def recommend_popular(
        self,
        top_n: int = 10,
        exclude_product_ids: Iterable[Any] | None = None,
        exclude_family_ids: Iterable[Any] | None = None,
    ) -> list[dict[str, Any]]:
        excluded_products = self._normalize_ids(exclude_product_ids or [])
        excluded_families = {str(value) for value in (exclude_family_ids or []) if value}
        rows: list[dict[str, Any]] = []

        for product_id in self.popular_product_ids:
            family_id = self.family_by_product.get(int(product_id), "")
            if int(product_id) in excluded_products or family_id in excluded_families:
                continue

            match = self.products[self.products["product_id"] == int(product_id)]
            if match.empty:
                continue

            rows.append(self._row_to_dict(match.iloc[0]))
            excluded_products.add(int(product_id))
            if family_id:
                excluded_families.add(family_id)

            if len(rows) >= top_n:
                break

        return rows

    def recommend_for_user(
        self,
        user_id: int,
        top_n: int = 10,
        exclude_product_ids: Iterable[Any] | None = None,
        exclude_family_ids: Iterable[Any] | None = None,
    ) -> list[dict[str, Any]]:
        excluded_products = self._normalize_ids(exclude_product_ids or [])
        excluded_products.update(self.user_seen.get(int(user_id), set()))

        excluded_families = {str(value) for value in (exclude_family_ids or []) if value}
        for product_id in list(excluded_products):
            family_id = self.family_by_product.get(int(product_id), "")
            if family_id:
                excluded_families.add(family_id)

        if self.model is None or user_id not in self.user_index:
            return self.recommend_popular(
                top_n=top_n,
                exclude_product_ids=excluded_products,
                exclude_family_ids=excluded_families,
            )

        user_idx = self.user_index[int(user_id)]
        if self.user_factors is None or self.item_factors is None:
            return self.recommend_popular(
                top_n=top_n,
                exclude_product_ids=excluded_products,
                exclude_family_ids=excluded_families,
            )

        scores = np.dot(self.user_factors[user_idx], self.item_factors.T)
        ranked_indices = np.argsort(scores)[::-1]

        recommended: list[dict[str, Any]] = []
        selected_families = set(excluded_families)

        for ranked_idx in ranked_indices:
            product_id = int(self.product_ids[int(ranked_idx)])
            family_id = self.family_by_product.get(product_id, "")

            if product_id in excluded_products or family_id in selected_families:
                continue

            match = self.products[self.products["product_id"] == product_id]
            if match.empty:
                continue

            recommended.append(self._row_to_dict(match.iloc[0]))
            excluded_products.add(product_id)
            if family_id:
                selected_families.add(family_id)

            if len(recommended) >= top_n:
                return recommended

        recommended.extend(
            self.recommend_popular(
                top_n=top_n - len(recommended),
                exclude_product_ids=excluded_products,
                exclude_family_ids=selected_families,
            )
        )
        return recommended[:top_n]
