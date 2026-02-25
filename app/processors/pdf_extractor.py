"""PDF extraction pipeline — text and images using PyMuPDF (fitz).

Extracts:
- Text from each page (structured)
- Embedded images (rendered at 200 DPI)
- Detection of architectural plans (by aspect ratio + content heuristics)
"""
import io
import base64
from dataclasses import dataclass, field
from loguru import logger

import fitz  # PyMuPDF


@dataclass
class PDFPage:
    """Extracted content from a single PDF page."""
    page_number: int
    text: str
    images: list[bytes] = field(default_factory=list)
    images_base64: list[str] = field(default_factory=list)


@dataclass
class PDFContent:
    """Full extracted content from a PDF."""
    pages: list[PDFPage]
    total_pages: int
    total_text: str
    total_images: int
    is_architectural: bool


async def extract_from_pdf(file_bytes: bytes) -> PDFContent:
    """Extract text and images from a PDF file.

    Args:
        file_bytes: Raw PDF bytes.

    Returns:
        PDFContent with per-page text, extracted images, and metadata.
    """
    doc = fitz.open(stream=file_bytes, filetype="pdf")
    pages: list[PDFPage] = []
    all_text_parts: list[str] = []
    total_images = 0
    landscape_pages = 0

    for page_num in range(len(doc)):
        page = doc[page_num]
        page_text = page.get_text("text")
        all_text_parts.append(page_text)

        # Track aspect ratio for architectural detection
        rect = page.rect
        if rect.width > rect.height * 1.3:
            landscape_pages += 1

        # Extract embedded images
        page_images: list[bytes] = []
        page_images_b64: list[str] = []

        image_list = page.get_images(full=True)
        for img_idx, img_info in enumerate(image_list):
            xref = img_info[0]
            try:
                base_image = doc.extract_image(xref)
                if base_image and base_image.get("image"):
                    img_bytes = base_image["image"]
                    # Only keep images larger than 10KB (skip tiny icons/logos)
                    if len(img_bytes) > 10240:
                        page_images.append(img_bytes)
                        page_images_b64.append(
                            base64.b64encode(img_bytes).decode("utf-8")
                        )
                        total_images += 1
            except Exception as e:
                logger.debug(
                    f"Failed to extract image {img_idx} from page {page_num}: {e}"
                )

        # If no embedded images found but page might be a scan, render as image
        if not page_images and len(page_text.strip()) < 50:
            try:
                pix = page.get_pixmap(dpi=200)
                img_bytes = pix.tobytes("jpeg")
                if len(img_bytes) > 10240:
                    page_images.append(img_bytes)
                    page_images_b64.append(
                        base64.b64encode(img_bytes).decode("utf-8")
                    )
                    total_images += 1
            except Exception as e:
                logger.debug(f"Failed to render page {page_num} as image: {e}")

        pages.append(
            PDFPage(
                page_number=page_num + 1,
                text=page_text,
                images=page_images,
                images_base64=page_images_b64,
            )
        )

    doc.close()

    total_text = "\n\n".join(all_text_parts)

    # Heuristic: architectural plan if mostly landscape + low text density
    text_density = len(total_text.strip()) / max(len(doc), 1)
    is_architectural = (
        landscape_pages > len(pages) * 0.5
        and text_density < 500
    )

    result = PDFContent(
        pages=pages,
        total_pages=len(pages),
        total_text=total_text,
        total_images=total_images,
        is_architectural=is_architectural,
    )

    logger.info(
        f"PDF extracted: {result.total_pages} pages, "
        f"{total_images} images, {len(total_text)} chars, "
        f"architectural={is_architectural}"
    )

    return result
