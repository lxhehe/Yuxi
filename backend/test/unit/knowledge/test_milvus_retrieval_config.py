from yuxi.knowledge.implementations.milvus import _retrieval_config_options


def test_milvus_retrieval_config_omits_graph_options():
    options = _retrieval_config_options()
    by_key = {option["key"]: option for option in options}

    assert "use_graph_retrieval" not in by_key
    assert "graph_max_nodes" not in by_key
    assert "graph_top_k" not in by_key
    assert by_key["reranker_model"]["depend_on"] == ("use_reranker", True)
