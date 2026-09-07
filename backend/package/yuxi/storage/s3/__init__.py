"""S3 兼容对象存储。"""

from .client import (
    ObjectStoreClient,
    StorageError,
    UploadResult,
    aupload_file_to_object_store,
    get_object_store_client,
)
from .utils import generate_unique_filename, get_file_size, upload_image_to_object_store

__all__ = [
    "ObjectStoreClient",
    "get_object_store_client",
    "aupload_file_to_object_store",
    "StorageError",
    "UploadResult",
    "get_file_size",
    "generate_unique_filename",
    "upload_image_to_object_store",
]
