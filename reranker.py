from sentence_transformers import CrossEncoder

_model = None


def get_reranker():
    """Возвращает singleton-экземпляр CrossEncoder-реранкера (BAAI/bge-reranker-v2-m3).
    При первом вызове загружает модель с диска; при последующих возвращает кэшированную."""
    global _model
    if _model is None:
        _model = CrossEncoder("BAAI/bge-reranker-v2-m3")
    return _model