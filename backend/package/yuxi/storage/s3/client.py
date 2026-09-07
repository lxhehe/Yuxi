"""S3 兼容对象存储客户端。"""

import asyncio
import json
import mimetypes
import os
from contextlib import asynccontextmanager
from datetime import timedelta
from io import BytesIO
from urllib.parse import quote, urlparse, urlsplit

from urllib3 import BaseHTTPResponse
from yuxi.utils import logger

from minio import Minio
from minio.error import S3Error


class StorageError(Exception):
    """存储相关异常基类"""

    pass


class UploadResult:
    """简化的上传结果"""

    def __init__(self, url: str, bucket_name: str, object_name: str):
        self.url = url
        self.bucket_name = bucket_name
        self.object_name = object_name


def normalize_public_object_url(value: str | None) -> str | None:
    """把历史 :9000/public/ 绝对 URL 收成同源 /minio/public/ 代理路径。"""
    if not value or value.startswith("/minio/public/"):
        return value
    try:
        parsed = urlsplit(value)
        if parsed.port != 9000 or not parsed.path.startswith("/public/"):
            return value
    except ValueError:
        return value
    public_base_url = (os.getenv("S3_PUBLIC_BASE_URL") or "/minio").rstrip("/")
    normalized = f"{public_base_url}{parsed.path}"
    if parsed.query:
        normalized = f"{normalized}?{parsed.query}"
    if parsed.fragment:
        normalized = f"{normalized}#{parsed.fragment}"
    return normalized


class ObjectStoreClient:
    """S3 兼容对象存储客户端。"""

    PUBLIC_READ_BUCKETS = {"public"}

    # 知识库相关的 bucket 名称；images 使用私有 bucket，图片统一经后端鉴权代理访问
    KB_BUCKETS = {
        "documents": "knowledgebases",
        "parsed": "knowledgebases",
        "images": "kb-images",
    }

    def __init__(self):
        self.endpoint = os.getenv("S3_ENDPOINT") or "http://rustfs:9000"
        self.access_key = os.getenv("S3_ACCESS_KEY") or "rustfsadmin"
        self.secret_key = os.getenv("S3_SECRET_KEY") or "rustfsadmin"
        self.public_base_url = (os.getenv("S3_PUBLIC_BASE_URL") or "/minio").rstrip("/")
        self._client = None

    @property
    def client(self) -> Minio:
        """获取底层 S3 SDK 客户端。"""
        if self._client is None:
            endpoint = self.endpoint
            if "://" in endpoint:
                endpoint = endpoint.split("://")[-1]

            self._client = Minio(
                endpoint=endpoint, access_key=self.access_key, secret_key=self.secret_key, secure=False
            )
        return self._client

    def ensure_bucket_exists(self, bucket_name: str) -> bool:
        """确保存储桶存在"""
        try:
            created = False
            if not self.client.bucket_exists(bucket_name=bucket_name):
                self.client.make_bucket(bucket_name=bucket_name)
                created = True
                logger.info(f"存储桶 '{bucket_name}' 已创建")

            self._ensure_public_read_access(bucket_name)

            if created and bucket_name in self.PUBLIC_READ_BUCKETS:
                logger.info(f"存储桶 '{bucket_name}' 已配置为公开可读")

            return True
        except S3Error as e:
            logger.error(f"存储桶 '{bucket_name}' 错误: {e}")
            raise StorageError(f"Error with bucket '{bucket_name}': {e}")
        except StorageError:
            raise

    def upload_file(
        self, bucket_name: str, object_name: str, data: bytes, content_type: str | None = None
    ) -> UploadResult:
        """上传文件并返回内部对象 URL。"""
        try:
            self.ensure_bucket_exists(bucket_name=bucket_name)

            resolved_content_type = content_type or self._guess_content_type(object_name)
            data_stream = BytesIO(data)
            result = self.client.put_object(
                bucket_name=bucket_name,
                object_name=object_name,
                data=data_stream,
                length=len(data),
                content_type=resolved_content_type,
            )

            assert result is not None
            if bucket_name in self.PUBLIC_READ_BUCKETS:
                url = f"{self.public_base_url}/{bucket_name}/{quote(object_name, safe='/')}"
            else:
                url = f"s3://{bucket_name}/{quote(object_name, safe='/')}"

            return UploadResult(url, bucket_name, object_name)

        except S3Error as e:
            error_msg = f"上传文件 '{object_name}' 失败: {e}"
            logger.error(error_msg)
            raise StorageError(error_msg)

    async def aupload_file(
        self,
        bucket_name: str,
        object_name: str,
        data: bytes,
        content_type: str | None = None,
    ) -> UploadResult:
        result = await asyncio.to_thread(
            self.upload_file, bucket_name=bucket_name, object_name=object_name, data=data, content_type=content_type
        )
        return result

    def upload_file_from_path(self, bucket_name: str, object_name: str, file_path: str) -> UploadResult:
        """从文件路径上传文件"""
        try:
            with open(file_path, "rb") as file_data:
                data = file_data.read()

            return self.upload_file(bucket_name, object_name, data)

        except FileNotFoundError:
            raise StorageError(f"文件 '{file_path}' 不存在")
        except Exception as e:
            raise StorageError(f"从路径上传文件失败: {e}")

    def _guess_content_type(self, object_name: str) -> str:
        """根据文件名猜测 MIME 类型"""
        guessed_type, _ = mimetypes.guess_type(object_name)
        if guessed_type:
            return guessed_type

        ext = object_name.split(".")[-1].lower()
        content_types = {
            "md": "text/markdown",
            "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "xls": "application/vnd.ms-excel",
            "zip": "application/zip",
            "webp": "image/webp",
            "bmp": "image/bmp",
            "tif": "image/tiff",
            "tiff": "image/tiff",
        }
        return content_types.get(ext, "application/octet-stream")

    def download_file(self, bucket_name: str, object_name: str) -> bytes:
        """下载文件"""
        response = None
        try:
            response = self.client.get_object(bucket_name=bucket_name, object_name=object_name)
            data = response.read()
            logger.info(f"成功下载 '{object_name}' 从存储桶 '{bucket_name}'")
            return data

        except S3Error as e:
            if e.code == "NoSuchKey":
                raise StorageError(f"对象 '{object_name}' 在存储桶 '{bucket_name}' 中不存在")
            raise StorageError(f"下载文件失败: {e}")
        finally:
            if response is not None:
                response.close()
                response.release_conn()

    async def adownload_response(self, bucket_name: str, object_name: str) -> BaseHTTPResponse:
        """异步下载文件"""
        try:
            response = await asyncio.to_thread(
                self.client.get_object,
                bucket_name=bucket_name,
                object_name=object_name,
            )
            return response

        except S3Error as e:
            if e.code == "NoSuchKey":
                raise StorageError(f"对象 '{object_name}' 在存储桶 '{bucket_name}' 中不存在")
            raise StorageError(f"下载文件失败: {e}")

    async def adownload_file(self, bucket_name: str, object_name: str) -> bytes:
        """异步下载文件"""
        response = None
        try:
            response = await asyncio.to_thread(self.client.get_object, bucket_name=bucket_name, object_name=object_name)
            data = await asyncio.to_thread(response.read)
            logger.info(f"成功下载 '{object_name}' 从存储桶 '{bucket_name}'")
            return data

        except S3Error as e:
            if e.code == "NoSuchKey":
                raise StorageError(f"对象 '{object_name}' 在存储桶 '{bucket_name}' 中不存在")
            raise StorageError(f"下载文件失败: {e}")
        finally:
            if response is not None:
                response.close()
                response.release_conn()

    def get_presigned_url(self, bucket_name: str, object_name: str, days=7) -> str:
        """生成预签名 GET URL，供内网对象经代理访问。"""
        res_url = self.client.get_presigned_url(
            method="GET", bucket_name=bucket_name, object_name=object_name, expires=timedelta(days=days)
        )
        return res_url

    def delete_file(self, bucket_name: str, object_name: str) -> bool:
        """删除文件"""
        try:
            self.client.remove_object(bucket_name=bucket_name, object_name=object_name)
            logger.info(f"成功删除 '{object_name}' 从存储桶 '{bucket_name}'")
            return True

        except S3Error as e:
            if e.code == "NoSuchKey":
                logger.warning(f"要删除的对象 '{object_name}' 不存在")
                return False
            raise StorageError(f"删除文件失败: {e}")

    async def adelete_file(self, bucket_name: str, object_name: str) -> bool:
        """删除文件"""
        result = await asyncio.to_thread(
            self.delete_file,
            bucket_name=bucket_name,
            object_name=object_name,
        )
        return result

    async def adelete_objects_by_prefix(self, bucket_name: str, prefix: str) -> int:
        """
        按前缀删除对象

        Args:
            bucket_name: bucket 名称
            prefix: 对象前缀

        Returns:
            删除的对象数量
        """
        deleted_count = 0

        def _delete_objects():
            nonlocal deleted_count
            try:
                objects = self.client.list_objects(bucket_name, prefix=prefix, recursive=True)
                for obj in objects:
                    self.client.remove_object(bucket_name, obj.object_name)
                    deleted_count += 1
            except S3Error as e:
                if e.code == "NoSuchBucket":
                    logger.warning(f"待清理的存储桶 '{bucket_name}' 不存在")
                    return
                raise StorageError(f"删除对象前缀失败: {bucket_name}/{prefix}: {e}") from e

        await asyncio.to_thread(_delete_objects)
        return deleted_count

    async def alist_object_metadata(self, bucket_name: str, prefix: str) -> list[dict]:
        """在线程池中列出过期清理所需的对象元数据。"""

        def list_metadata() -> list[dict]:
            try:
                return [
                    {
                        "object_name": str(item.object_name),
                        "last_modified": item.last_modified,
                    }
                    for item in self.client.list_objects(bucket_name, prefix=prefix, recursive=True)
                ]
            except S3Error as exc:
                raise StorageError(f"列出对象前缀失败: {bucket_name}/{prefix}: {exc}") from exc

        return await asyncio.to_thread(list_metadata)

    async def adelete_bucket(self, bucket_name: str) -> bool:
        """
        删除 bucket（先删除所有对象，再删除 bucket）

        Args:
            bucket_name: bucket 名称

        Returns:
            是否成功
        """
        try:
            # 先删除所有对象
            await self.adelete_objects_by_prefix(bucket_name, "")
            # 再删除 bucket
            await asyncio.to_thread(self.client.remove_bucket, bucket_name)
            logger.info(f"成功删除 bucket: {bucket_name}")
            return True
        except S3Error as e:
            if e.code == "NoSuchBucket":
                logger.warning(f"bucket 不存在: {bucket_name}")
                return False
            raise StorageError(f"删除 bucket 失败: {e}")

    def file_exists(self, bucket_name: str, object_name: str) -> bool:
        """检查文件是否存在"""
        try:
            self.client.stat_object(bucket_name=bucket_name, object_name=object_name)
            return True
        except S3Error as e:
            if e.code == "NoSuchKey":
                return False
            raise StorageError(f"检查文件存在性失败: {e}")

    def stat_file(self, bucket_name: str, object_name: str) -> int | None:
        """获取文件大小（字节），文件不存在时返回 None"""
        try:
            stat = self.client.stat_object(bucket_name=bucket_name, object_name=object_name)
            return stat.size
        except S3Error as e:
            if e.code == "NoSuchKey":
                return None
            raise StorageError(f"获取文件信息失败: {e}")

    async def astat_file(self, bucket_name: str, object_name: str) -> int | None:
        """异步获取文件大小（字节），文件不存在时返回 None"""
        return await asyncio.to_thread(self.stat_file, bucket_name, object_name)

    def _ensure_public_read_access(self, bucket_name: str) -> None:
        """设置存储桶策略，允许公开读取对象"""
        if bucket_name not in self.PUBLIC_READ_BUCKETS:
            return

        policy = {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Principal": {"AWS": ["*"]},
                    "Action": ["s3:GetObject"],
                    "Resource": [f"arn:aws:s3:::{bucket_name}/*"],
                },
            ],
        }

        try:
            self.client.set_bucket_policy(bucket_name=bucket_name, policy=json.dumps(policy))
        except S3Error as e:
            logger.warning(f"设置存储桶 '{bucket_name}' 公共读取策略失败: {e}")
            raise StorageError(f"无法设置存储桶公共访问策略: {e}")

    @asynccontextmanager
    async def temp_file_from_url(
        self,
        url: str,
        allowed_extensions: list[str] | None = None,
    ):
        """
        从对象 URL 下载到临时文件，退出时删除。

        接受 `s3://`、历史 `minio://` 以及 `http(s)://host/bucket/key`。
        """
        import tempfile

        if not url or not isinstance(url, str):
            raise StorageError("URL 不能为空")

        url = url.strip()
        parsed = urlparse(url)

        if parsed.scheme in {"s3", "minio"}:
            bucket_name = parsed.netloc
            object_name = parsed.path.lstrip("/")
            if not bucket_name or not object_name:
                raise StorageError("无法解析对象 URL")
        elif parsed.scheme in {"http", "https"}:
            endpoint_host = self.endpoint.split("://")[-1].split(":")[0]
            url_host = parsed.netloc.split(":")[0]

            if endpoint_host != url_host and url_host != os.environ.get("HOST_IP", "localhost"):
                raise StorageError(f"不允许的外部 URL: {url_host}")

            if ".." in url or "\\" in url:
                raise StorageError("URL 包含路径遍历字符")

            path_parts = parsed.path.lstrip("/").split("/", 1)
            if len(path_parts) != 2:
                raise StorageError("无法解析对象 URL")

            bucket_name, object_name = path_parts
        else:
            raise StorageError("无效的对象 URL，只允许 s3/minio/http/https")

        if allowed_extensions and not any(url.endswith(ext) for ext in allowed_extensions):
            raise StorageError(f"文件扩展名不符合要求，允许: {', '.join(allowed_extensions)}")

        file_data = await self.adownload_file(bucket_name, object_name)
        logger.info(f"成功下载对象: {object_name} ({len(file_data)} bytes)")

        if allowed_extensions:
            suffix = next((ext for ext in allowed_extensions if url.endswith(ext)), ".tmp")
        else:
            suffix = f".{object_name.split('.')[-1]}"

        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(mode="wb", suffix=suffix, delete=False) as temp_file:
                temp_file.write(file_data)
                temp_path = temp_file.name

            logger.info(f"文件已下载到临时路径: {temp_path}")
            yield temp_path

        finally:
            if temp_path and os.path.exists(temp_path):
                try:
                    os.unlink(temp_path)
                    logger.info(f"已删除临时文件: {temp_path}")
                except Exception as e:
                    logger.warning(f"删除临时文件失败: {e}")


_default_client = None


def get_object_store_client() -> ObjectStoreClient:
    """获取进程内共享的对象存储客户端。"""
    global _default_client
    if _default_client is None:
        _default_client = ObjectStoreClient()
    return _default_client


async def aupload_file_to_object_store(bucket_name: str, file_name: str, data: bytes) -> str:
    """
    通过字节上传文件并返回资源 URL。
    MIME 类型由客户端根据 object_name 推断。
    """
    client = get_object_store_client()
    upload_result = await client.aupload_file(bucket_name, file_name, data)
    return upload_result.url
