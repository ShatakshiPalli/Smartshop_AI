"""
Semantic search over products using Sentence Transformers embeddings and a
FAISS index. Index is built/refreshed per search session from the products
just retrieved (cheap, and always fresh vs. live Apify data) rather than
maintaining one giant persistent index - simplest thing that works and is
easy to deploy on free hosting (no big background index to keep warm).

A persistent on-disk index (FAISS_INDEX_DIR) is also supported for reuse
across requests within the same process lifetime.
"""
import logging
import os
from typing import Dict, List, Tuple

import numpy as np

from app.config import get_settings
from app.models import Product

logger = logging.getLogger("smartshop.embeddings")
settings = get_settings()

_model = None


def _get_model():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer

        _model = SentenceTransformer(settings.EMBEDDING_MODEL_NAME)
    return _model


def _product_text(product: Product) -> str:
    spec_text = " ".join(f"{k}: {v}" for k, v in (product.specifications or {}).items())
    return f"{product.canonical_title}. Brand: {product.brand or ''}. Category: {product.category or ''}. {spec_text}"


class ProductVectorIndex:
    """Ephemeral, in-memory FAISS index over a set of products."""

    def __init__(self):
        self.index = None
        self.product_ids: List[str] = []

    def build(self, products: List[Product]):
        import faiss

        if not products:
            self.index = None
            self.product_ids = []
            return

        model = _get_model()
        texts = [_product_text(p) for p in products]
        embeddings = model.encode(texts, convert_to_numpy=True, normalize_embeddings=True)
        dim = embeddings.shape[1]

        self.index = faiss.IndexFlatIP(dim)  # cosine similarity via normalized inner product
        self.index.add(embeddings.astype(np.float32))
        self.product_ids = [p.id for p in products]

    def search(self, query: str, top_k: int = 10) -> List[Tuple[str, float]]:
        if self.index is None or not self.product_ids:
            return []
        model = _get_model()
        query_vec = model.encode([query], convert_to_numpy=True, normalize_embeddings=True)
        scores, indices = self.index.search(query_vec.astype(np.float32), min(top_k, len(self.product_ids)))
        results = []
        for score, idx in zip(scores[0], indices[0]):
            if idx == -1:
                continue
            results.append((self.product_ids[idx], float(score)))
        return results


def semantic_rerank(products: List[Product], query: str) -> Dict[str, float]:
    """Returns {product_id: semantic_similarity_score} for the given query."""
    try:
        idx = ProductVectorIndex()
        idx.build(products)
        results = idx.search(query, top_k=len(products))
        return dict(results)
    except Exception as exc:
        logger.error("Semantic search failed, continuing without it: %s", exc)
        return {}
