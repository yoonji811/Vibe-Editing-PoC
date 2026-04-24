"""Cloudinary image storage service."""
import logging
import os
from typing import Optional

import cloudinary
import cloudinary.uploader

logger = logging.getLogger(__name__)

_cloud_name = os.getenv("CLOUDINARY_CLOUD_NAME")
_api_key = os.getenv("CLOUDINARY_API_KEY")
_api_secret = os.getenv("CLOUDINARY_API_SECRET")

_configured = bool(_cloud_name and _api_key and _api_secret)

if _configured:
    cloudinary.config(
        cloud_name=_cloud_name,
        api_key=_api_key,
        api_secret=_api_secret,
        secure=True,
    )
    logger.info("Cloudinary configured: cloud_name=%s", _cloud_name)
else:
    logger.warning("Cloudinary not configured — image URLs will not be stored")


def upload_image(b64: str, public_id: str) -> Optional[str]:
    """Upload base64 image to Cloudinary and return the secure URL.

    Returns None when Cloudinary credentials are not configured or upload fails.
    Never raises — a failed upload must not break the session/edit flow.
    """
    if not _configured:
        return None
    try:
        data_uri = f"data:image/jpeg;base64,{b64}"
        result = cloudinary.uploader.upload(
            data_uri,
            public_id=public_id,
            folder="vibe-editing",
            overwrite=True,
            resource_type="image",
        )
        return result["secure_url"]
    except Exception as exc:
        logger.error("Cloudinary upload failed for %s: %s", public_id, exc)
        return None
