"""Cloudinary image storage service."""
import base64
import os

import cloudinary
import cloudinary.uploader

cloudinary.config(
    cloud_name=os.getenv("CLOUDINARY_CLOUD_NAME"),
    api_key=os.getenv("CLOUDINARY_API_KEY"),
    api_secret=os.getenv("CLOUDINARY_API_SECRET"),
    secure=True,
)


def upload_image(b64: str, public_id: str) -> str:
    """Upload base64 image to Cloudinary and return the secure URL."""
    data_uri = f"data:image/jpeg;base64,{b64}"
    result = cloudinary.uploader.upload(
        data_uri,
        public_id=public_id,
        folder="vibe-editing",
        overwrite=True,
        resource_type="image",
    )
    return result["secure_url"]
