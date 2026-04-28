from pydantic import BaseModel


class AwinBannerRequest(BaseModel):
    filenames: list[str]
    description: str
    tag: str
    target_url: str
    alt_text: str
    image_source_stem: str
