import numpy as np
from sentence_transformers import SentenceTransformer

_model = None


def get_embedder():
    global _model
    if _model is None:
        _model = SentenceTransformer("BAAI/bge-m3")
    return _model


def create_embedding(text: str) -> bytes:
    vector = get_embedder().encode(text, normalize_embeddings=True)
    return np.array(vector, dtype=np.float32).tobytes()


def bytes_to_vector(blob):
    return np.frombuffer(blob, dtype=np.float32)