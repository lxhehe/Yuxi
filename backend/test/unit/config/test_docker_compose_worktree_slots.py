from copy import deepcopy
import json
import os
from pathlib import Path

import pytest
import yaml


STATE_ROOT = "${YUXI_STATE_DIR:-./docker/volumes}"
IMAGE_PREFIX = "${COMPOSE_PROJECT_NAME:-yuxi}"
PORT_MARKERS = {
    "api": {"${YUXI_API_PORT:-5050}:5050"},
    "web": {"${YUXI_WEB_PORT:-5173}:5173"},
    "sandbox-provisioner": {"127.0.0.1:${YUXI_SANDBOX_PORT:-8002}:8002"},
    "rustfs": {
        "127.0.0.1:${YUXI_S3_API_PORT:-9000}:9000",
        "127.0.0.1:${YUXI_S3_CONSOLE_PORT:-9001}:9001",
    },
    "milvus": {
        "127.0.0.1:${YUXI_MILVUS_PORT:-19530}:19530",
        "127.0.0.1:${YUXI_MILVUS_HEALTH_PORT:-9091}:9091",
    },
    "postgres": {"127.0.0.1:${YUXI_POSTGRES_PORT:-5432}:5432"},
    "redis": {"127.0.0.1:${YUXI_REDIS_PORT:-6379}:6379"},
    "mineru-api": {"127.0.0.1:${YUXI_MINERU_PORT:-30001}:30001"},
    "paddlex": {"127.0.0.1:${YUXI_PADDLEX_PORT:-8080}:8080"},
}
LOCAL_IMAGE_SUFFIXES = {
    "api": "-api:",
    "worker": "-api:",
    "storage-migrator": "-api:",
    "sandbox-provisioner": "-sandbox-provisioner:",
    "web": "-web:",
    "mineru-api": "-mineru:",
    "paddlex": "-paddlex:",
}


def _project_root() -> Path:
    """定位包含 Compose 文件的仓库根目录。"""
    configured = os.environ.get("YUXI_PROJECT_ROOT")
    if configured:
        return Path(configured)

    for parent in Path(__file__).resolve().parents:
        if (parent / "docker-compose.yml").exists():
            return parent
    pytest.skip("当前测试环境未挂载仓库根目录")


def _load_compose(filename: str = "docker-compose.yml") -> dict:
    """读取未插值的 Compose 契约。"""
    return yaml.safe_load((_project_root() / filename).read_text())


def _slot_isolation_violations(compose: dict) -> set[str]:
    """报告会让两个开发槽位争用宿主资源的 Compose 配置。"""
    violations: set[str] = set()
    services = compose["services"]

    for service_name, service in services.items():
        if "container_name" in service:
            violations.add(f"container:{service_name}")
        for volume in service.get("volumes") or []:
            if isinstance(volume, str):
                source = volume.split(":", 1)[0]
            else:
                source = str(volume.get("source") or "")
            if source.startswith("./docker/volumes"):
                violations.add(f"state:{service_name}:{source}")

    if "name" in compose["networks"]["app-network"]:
        violations.add("network:app-network")

    for service_name, expected_ports in PORT_MARKERS.items():
        actual_ports = set(services[service_name].get("ports") or [])
        if actual_ports != expected_ports:
            violations.add(f"ports:{service_name}")

    for service_name, suffix in LOCAL_IMAGE_SUFFIXES.items():
        image = str(services[service_name].get("image") or "")
        if not image.startswith(f"{IMAGE_PREFIX}{suffix}"):
            violations.add(f"image:{service_name}")

    provisioner_env = set(services["sandbox-provisioner"]["environment"])
    expected_prefix = "${SANDBOX_DOCKER_NETWORK_PREFIX:-${COMPOSE_PROJECT_NAME:-yuxi}-sandbox}"
    if f"DOCKER_NETWORK_PREFIX={expected_prefix}" not in provisioner_env:
        violations.add("sandbox:network-prefix")
    expected_container = "${SANDBOX_DOCKER_SANDBOX_PREFIX:-${COMPOSE_PROJECT_NAME:-yuxi}-sandbox}"
    if f"DOCKER_SANDBOX_PREFIX={expected_container}" not in provisioner_env:
        violations.add("sandbox:container-prefix")

    return violations


def test_development_compose_is_parameterized_for_parallel_worktree_slots() -> None:
    """开发 Compose 的宿主资源必须由项目名、状态根和端口共同隔离。"""
    compose = _load_compose()

    assert _slot_isolation_violations(compose) == set()

    state_sources = {
        str(volume.get("source"))
        for service in compose["services"].values()
        for volume in service.get("volumes") or []
        if isinstance(volume, dict) and str(volume.get("source") or "").startswith(STATE_ROOT)
    }
    assert f"{STATE_ROOT}/postgresql" in state_sources
    assert f"{STATE_ROOT}/redis" in state_sources
    assert f"{STATE_ROOT}/milvus/milvus" in state_sources
    assert f"{STATE_ROOT}/rustfs/data" in state_sources
    assert f"{STATE_ROOT}/yuxi/threads" in state_sources


def test_slot_isolation_guard_rejects_fixed_host_resources() -> None:
    """负控证明固定容器、网络、端口、镜像或状态路径会被拒绝。"""
    compose = deepcopy(_load_compose())
    compose["services"]["api"]["container_name"] = "api-dev"
    compose["services"]["api"]["ports"] = ["5050:5050"]
    compose["services"]["api"]["image"] = "yuxi-api:latest"
    compose["services"]["postgres"]["volumes"][0]["source"] = "./docker/volumes/postgresql"
    compose["networks"]["app-network"]["name"] = "yuxi-app-network"

    assert {
        "container:api",
        "ports:api",
        "image:api",
        "state:postgres:./docker/volumes/postgresql",
        "network:app-network",
    } <= _slot_isolation_violations(compose)


def test_production_compose_keeps_existing_deployment_image_identity() -> None:
    """开发槽位参数化不得改变生产 Compose 的镜像身份。"""
    compose = _load_compose("docker-compose.prod.yml")

    assert compose["services"]["api"]["image"].startswith("yuxi-api:${YUXI_VERSION:-")
    assert compose["services"]["web"]["image"].startswith("yuxi-web:${YUXI_VERSION:-")
    assert "COMPOSE_PROJECT_NAME" not in compose["services"]["api"]["image"]


def test_host_test_runner_probes_current_compose_slot() -> None:
    """测试运行器必须通过 Compose service 探测当前槽位。"""
    source = (_project_root() / "backend/test/run_tests.sh").read_text()

    assert "docker compose exec -T api curl -fsS http://localhost:5050/api/system/health" in source
    assert "if curl -s http://localhost:5050/api/system/health" not in source


def _forbidden_object_store_images(text: str) -> list[str]:
    hits: list[str] = []
    if "minio/minio:" in text:
        hits.append("minio")
    if "neo4j:" in text:
        hits.append("neo4j")
    return hits


def test_shipping_compose_uses_pinned_rustfs_without_minio_or_neo4j() -> None:
    """默认拓扑必须钉死 RustFS，且不能再带 MinIO 或 Neo4j 进程。"""
    for filename in ("docker-compose.yml", "docker-compose.prod.yml"):
        text = (_project_root() / filename).read_text()
        assert "rustfs/rustfs:1.0.0-rc.5" in text
        assert _forbidden_object_store_images(text) == []

    compose = _load_compose()
    services = compose["services"]
    assert "graph" not in services
    assert "minio" not in services
    assert services["rustfs"]["image"] == "rustfs/rustfs:1.0.0-rc.5"
    assert services["milvus"]["environment"]["MINIO_ADDRESS"] == "rustfs:9000"
    assert services["api"]["environment"]["S3_ENDPOINT"] == "${S3_ENDPOINT:-http://rustfs:9000}"


def test_shipping_image_guard_rejects_restored_minio_or_neo4j() -> None:
    """负控证明恢复 MinIO 或 Neo4j 镜像行会被拒绝。"""
    text = (_project_root() / "docker-compose.yml").read_text()
    assert "minio" in _forbidden_object_store_images(text + "\n    image: minio/minio:RELEASE.2023-03-20T20-16-18Z\n")
    assert "neo4j" in _forbidden_object_store_images(text + "\n    image: neo4j:5.26.29\n")


def test_init_and_save_scripts_pull_rustfs_instead_of_minio_and_neo4j() -> None:
    """镜像清单必须与 Compose 一致，不能再导出 MinIO 或 Neo4j。"""
    files = (
        "scripts/init.sh",
        "scripts/init.ps1",
        "docker/save_docker_images.sh",
        "docker/save_docker_images.ps1",
    )
    for relative in files:
        text = (_project_root() / relative).read_text()
        assert "rustfs/rustfs:1.0.0-rc.5" in text
        assert _forbidden_object_store_images(text) == []


def test_python_and_frontend_direct_deps_drop_graph_packages() -> None:
    """图谱专用直接依赖不得再出现在 lock 或 package.json 中。"""
    uv_lock = (_project_root() / "backend/uv.lock").read_text()
    assert 'name = "neo4j"' not in uv_lock
    package = json.loads((_project_root() / "web/package.json").read_text())
    deps = {**package.get("dependencies", {}), **package.get("devDependencies", {})}
    assert "@antv/g6" not in deps
    assert "d3" not in deps
    pnpm_lock = (_project_root() / "web/pnpm-lock.yaml").read_text()
    assert "@antv/g6@" not in pnpm_lock
    assert "'@antv/g6':" not in pnpm_lock
