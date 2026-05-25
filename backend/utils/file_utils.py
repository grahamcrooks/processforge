import base64
from api.models.schemas import GeneratedFile


def encode_file(filename: str, content: bytes, media_type: str) -> GeneratedFile:
    return GeneratedFile(
        filename=filename,
        content_base64=base64.b64encode(content).decode(),
        media_type=media_type,
    )
