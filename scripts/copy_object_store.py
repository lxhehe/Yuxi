#!/usr/bin/env python3
"""一次性把旧 S3 兼容端点上的对象复制到 RustFS。

默认 Compose 不再运行 MinIO。切流量前必须对账对象数，并对抽样对象做 Get。
不要把旧 MinIO 数据目录挂到 RustFS。

环境变量：

- SOURCE_ENDPOINT / SOURCE_ACCESS_KEY / SOURCE_SECRET_KEY
- DEST_ENDPOINT / DEST_ACCESS_KEY / DEST_SECRET_KEY
- BUCKETS：逗号分隔，默认 public,knowledgebases,kb-images,a-bucket
"""

from __future__ import annotations

import os
import sys
from io import BytesIO

from minio import Minio
from minio.error import S3Error


DEFAULT_BUCKETS = ("public", "knowledgebases", "kb-images", "a-bucket")


def _client(endpoint: str, access_key: str, secret_key: str) -> Minio:
    host = endpoint.split("://", 1)[-1]
    return Minio(host, access_key=access_key, secret_key=secret_key, secure=endpoint.startswith("https://"))


def _require_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise SystemExit(f"缺少环境变量 {name}")
    return value


def _list_names(client: Minio, bucket: str) -> list[str]:
    return [item.object_name for item in client.list_objects(bucket, recursive=True) if item.object_name]


def copy_bucket(source: Minio, dest: Minio, bucket: str) -> tuple[int, int]:
    """复制一个 bucket，返回 (源对象数, 目标对象数)。"""
    if not dest.bucket_exists(bucket):
        dest.make_bucket(bucket)

    names = []
    try:
        names = _list_names(source, bucket)
    except S3Error as exc:
        if exc.code == "NoSuchBucket":
            print(f"{bucket}: 源端不存在，跳过")
            return 0, 0
        raise

    for object_name in names:
        response = source.get_object(bucket, object_name)
        try:
            data = response.read()
        finally:
            response.close()
            response.release_conn()
        dest.put_object(bucket, object_name, BytesIO(data), length=len(data))

    dest_names = _list_names(dest, bucket)
    return len(names), len(dest_names)


def main() -> int:
    source = _client(
        _require_env("SOURCE_ENDPOINT"),
        _require_env("SOURCE_ACCESS_KEY"),
        _require_env("SOURCE_SECRET_KEY"),
    )
    dest = _client(
        _require_env("DEST_ENDPOINT"),
        _require_env("DEST_ACCESS_KEY"),
        _require_env("DEST_SECRET_KEY"),
    )
    buckets = tuple(item.strip() for item in os.getenv("BUCKETS", ",".join(DEFAULT_BUCKETS)).split(",") if item.strip())
    mismatched = False
    for bucket in buckets:
        source_count, dest_count = copy_bucket(source, dest, bucket)
        print(f"{bucket}: source={source_count} dest={dest_count}")
        if source_count != dest_count:
            mismatched = True
    if mismatched:
        print("对象数量不一致，不要切流量", file=sys.stderr)
        return 1
    print("对象数量一致。抽样 Get 并做一次知识库检索后再切流量。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
