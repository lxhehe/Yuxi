from server.routers import router
from server.routers.knowledge_router import knowledge


def _route_paths(app_router) -> list[str]:
    paths: list[str] = []
    for route in app_router.routes:
        path = getattr(route, "path", None)
        if path:
            paths.append(path)
        nested = getattr(route, "app", None) or getattr(route, "router", None)
        if nested is not None and nested is not app_router and hasattr(nested, "routes"):
            paths.extend(_route_paths(nested))
    return paths


def test_graph_routes_are_not_registered():
    """知识图谱 HTTP 入口不得再挂载。"""
    paths = _route_paths(router) + _route_paths(knowledge)
    assert not any("graph-build" in path or path.rstrip("/").endswith("/graph") or "/graph/" in path for path in paths)


def test_mindmap_routes_remain_registered():
    """知识导图入口必须保留。"""
    paths = _route_paths(knowledge)
    assert any(path.endswith("/mindmap") for path in paths)


def test_knowledge_base_tools_keep_mindmap_without_graph_tools():
    """knowledge-base 工具保留导图，不再暴露图谱工具。"""
    from yuxi.agents.toolkits.kbs import tools as kbs_tools

    assert getattr(kbs_tools.get_mindmap, "name", None) == "get_mindmap"
    assert not hasattr(kbs_tools, "query_graph")
    assert not hasattr(kbs_tools, "build_graph")
