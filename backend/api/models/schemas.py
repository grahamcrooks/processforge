from pydantic import BaseModel
from typing import Optional


class BrandingConfig(BaseModel):
    org_name: Optional[str] = None
    primary_colour: Optional[str] = None  # hex e.g. "#0057B8"
    logo_base64: Optional[str] = None     # base64-encoded image


class GenerateRequest(BaseModel):
    generate_bpin: bool = False
    branding: Optional[BrandingConfig] = None


class GeneratedFile(BaseModel):
    filename: str
    content_base64: str
    media_type: str


class ImageConfidence(BaseModel):
    filename: str
    score: int                      # 0–100
    readability: str                # "high" | "medium" | "low"
    notes: str
    unclear_elements: list[str] = []  # specific labels/areas Claude couldn't read well
    steps_extracted: int
    lanes_identified: int
    gateways_found: int
    decisions_extracted: int
    warnings: list[str] = []
    tiled: bool = False             # True if image was split into tiles for extraction
    tile_count: int = 1             # number of tiles used (1 = no tiling)
    image_width: int = 0
    image_height: int = 0


class GenerateResponse(BaseModel):
    files: list[GeneratedFile]
    warnings: list[str] = []
    confidence_scores: list[ImageConfidence] = []


class HealthResponse(BaseModel):
    status: str
    version: str
