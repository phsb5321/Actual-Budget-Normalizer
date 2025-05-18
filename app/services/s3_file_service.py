"""S3FileService provides S3-backed file operations for the app."""

import boto3
from botocore.exceptions import ClientError

from app.core.settings import get_settings


class S3FileService:
    """Service for S3 file operations: upload, download, list, ensure bucket."""

    def __init__(self) -> None:
        """Initialize S3FileService and ensure the bucket exists."""
        settings = get_settings()
        self.s3 = boto3.client(
            "s3",
            endpoint_url=settings.S3_ENDPOINT_URL,
            aws_access_key_id=settings.S3_ACCESS_KEY,
            aws_secret_access_key=settings.S3_SECRET_KEY,
        )
        self.bucket = settings.S3_BUCKET
        self.ensure_bucket()

    def ensure_bucket(self) -> None:
        """Ensure the S3 bucket exists, create if not present."""
        try:
            self.s3.head_bucket(Bucket=self.bucket)
        except ClientError:
            self.s3.create_bucket(Bucket=self.bucket)

    def upload_fileobj(self, key: str, data: bytes) -> None:
        """Upload a file object to S3 under the given key."""
        self.s3.put_object(Bucket=self.bucket, Key=str(key), Body=data)

    def download_fileobj(self, key: str) -> bytes:
        """Download a file object from S3 by key."""
        obj = self.s3.get_object(Bucket=self.bucket, Key=str(key))
        return obj["Body"].read()

    def list_files(self, prefix: str = "") -> list[str]:
        """List files in S3 with the given prefix."""
        resp = self.s3.list_objects_v2(Bucket=self.bucket, Prefix=str(prefix))
        return [item["Key"] for item in resp.get("Contents", [])]

    def file_exists(self, key: str) -> bool:
        """Check if a file exists in S3 by key."""
        try:
            self.s3.head_object(Bucket=self.bucket, Key=str(key))
        except ClientError:
            return False
        else:
            return True
