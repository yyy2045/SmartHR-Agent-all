import json
import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from functools import lru_cache
from io import BytesIO
from pathlib import Path
from typing import Any, Protocol


class ResumeParseError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class OCRLine:
    text: str
    confidence: float | None = None


@dataclass(frozen=True)
class ParsedSegment:
    source_type: str
    source_index: int
    raw_text: str
    normalized_text: str
    page_number: int | None = None
    paragraph_index: int | None = None
    ocr_confidence: float | None = None


@dataclass(frozen=True)
class ParseResult:
    extraction_method: str
    segments: list[ParsedSegment]


class OCREngine(Protocol):
    def recognize(self, image_bytes: bytes) -> list[OCRLine]: ...


def normalize_resume_text(value: str) -> str:
    value = unicodedata.normalize("NFKC", value)
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    value = "".join(
        character
        for character in value
        if character in {"\n", "\t"} or unicodedata.category(character) != "Cc"
    )
    lines = [re.sub(r"[\t \u00a0]+", " ", line).strip() for line in value.split("\n")]
    normalized_lines: list[str] = []
    previous_blank = True
    for line in lines:
        if line:
            normalized_lines.append(line)
            previous_blank = False
        elif not previous_blank:
            normalized_lines.append("")
            previous_blank = True
    return "\n".join(normalized_lines).strip()


def _average_confidence(lines: list[OCRLine]) -> float | None:
    scores = [line.confidence for line in lines if line.confidence is not None]
    return sum(scores) / len(scores) if scores else None


def _coerce_v2_ocr_lines(value: Any) -> list[OCRLine]:
    lines: list[OCRLine] = []

    def visit(item: Any) -> None:
        if (
            isinstance(item, (list, tuple))
            and len(item) == 2
            and isinstance(item[1], (list, tuple))
            and item[1]
            and isinstance(item[1][0], str)
        ):
            confidence = float(item[1][1]) if len(item[1]) > 1 else None
            lines.append(OCRLine(text=item[1][0], confidence=confidence))
            return
        if isinstance(item, (list, tuple)):
            for child in item:
                visit(child)

    visit(value)
    return lines


def _coerce_v3_ocr_lines(value: Any) -> list[OCRLine]:
    lines: list[OCRLine] = []
    items = value if isinstance(value, (list, tuple)) else [value]
    for item in items:
        payload = getattr(item, "json", item)
        payload = payload() if callable(payload) else payload
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except json.JSONDecodeError:
                continue
        if not isinstance(payload, dict):
            continue
        result = payload.get("res", payload)
        texts = result.get("rec_texts") or result.get("texts") or []
        scores = result.get("rec_scores") or result.get("scores") or []
        for index, text in enumerate(texts):
            confidence = float(scores[index]) if index < len(scores) else None
            lines.append(OCRLine(text=str(text), confidence=confidence))
    return lines


class PaddleOCREngine:
    def __init__(self) -> None:
        try:
            from paddleocr import PaddleOCR
        except ImportError as error:
            raise ResumeParseError(
                "ocr_unavailable",
                "PaddleOCR 尚未安装或加载失败",
            ) from error

        try:
            self._engine = PaddleOCR(
                lang="ch",
                use_doc_orientation_classify=False,
                use_doc_unwarping=False,
                use_textline_orientation=True,
                enable_mkldnn=False,
            )
        except TypeError:
            self._engine = PaddleOCR(lang="ch", use_angle_cls=True, show_log=False)

    def recognize(self, image_bytes: bytes) -> list[OCRLine]:
        try:
            import numpy as np
            from PIL import Image

            image = np.asarray(Image.open(BytesIO(image_bytes)).convert("RGB"))
            if hasattr(self._engine, "predict"):
                lines = _coerce_v3_ocr_lines(self._engine.predict(input=image))
            else:
                lines = _coerce_v2_ocr_lines(self._engine.ocr(image, cls=True))
        except ResumeParseError:
            raise
        except Exception as error:
            raise ResumeParseError("ocr_failed", "OCR 识别失败") from error
        return [line for line in lines if normalize_resume_text(line.text)]


@lru_cache(maxsize=1)
def get_ocr_engine() -> OCREngine:
    return PaddleOCREngine()


def _ocr_segment(
    image_bytes: bytes,
    *,
    engine: OCREngine,
    source_type: str,
    source_index: int,
    page_number: int | None = None,
) -> ParsedSegment | None:
    lines = engine.recognize(image_bytes)
    raw_text = "\n".join(line.text for line in lines)
    normalized_text = normalize_resume_text(raw_text)
    if not normalized_text:
        return None
    return ParsedSegment(
        source_type=source_type,
        source_index=source_index,
        page_number=page_number,
        raw_text=raw_text,
        normalized_text=normalized_text,
        ocr_confidence=_average_confidence(lines),
    )


def _parse_pdf(
    path: Path,
    *,
    ocr_engine: OCREngine | None,
    min_text_characters: int,
    render_scale: float,
) -> ParseResult:
    try:
        import fitz

        document = fitz.open(path)
    except ImportError as error:
        raise ResumeParseError("parser_unavailable", "PDF 解析组件尚未安装") from error
    except Exception as error:
        raise ResumeParseError("invalid_pdf", "PDF 文件损坏或无法读取") from error

    try:
        if document.needs_pass:
            raise ResumeParseError("encrypted_pdf", "PDF 已加密，暂时无法解析")
        if document.page_count == 0:
            raise ResumeParseError("empty_text", "PDF 不包含可解析页面")

        direct_segments: list[ParsedSegment] = []
        direct_character_count = 0
        for index, page in enumerate(document):
            raw_text = page.get_text("text") or ""
            normalized_text = normalize_resume_text(raw_text)
            direct_character_count += len(re.sub(r"\s+", "", normalized_text))
            if normalized_text:
                direct_segments.append(
                    ParsedSegment(
                        source_type="pdf_page",
                        source_index=index + 1,
                        page_number=index + 1,
                        raw_text=raw_text,
                        normalized_text=normalized_text,
                    )
                )

        if direct_character_count >= min_text_characters:
            return ParseResult(extraction_method="pdf_text", segments=direct_segments)

        engine = ocr_engine or get_ocr_engine()
        ocr_segments: list[ParsedSegment] = []
        matrix = fitz.Matrix(render_scale, render_scale)
        for index, page in enumerate(document):
            image_bytes = page.get_pixmap(matrix=matrix, alpha=False).tobytes("png")
            segment = _ocr_segment(
                image_bytes,
                engine=engine,
                source_type="pdf_page",
                source_index=index + 1,
                page_number=index + 1,
            )
            if segment:
                ocr_segments.append(segment)
        if not ocr_segments:
            raise ResumeParseError("empty_text", "PDF 文本提取和 OCR 均未识别到有效内容")
        return ParseResult(extraction_method="pdf_ocr", segments=ocr_segments)
    finally:
        document.close()


def _iter_docx_paragraph_text(document: Any) -> Iterable[tuple[int, str]]:
    try:
        from docx.table import Table
        from docx.text.paragraph import Paragraph
    except ImportError as error:
        raise ResumeParseError("parser_unavailable", "DOCX 解析组件尚未安装") from error

    index = 0
    for child in document.element.body.iterchildren():
        if child.tag.endswith("}p"):
            index += 1
            yield index, Paragraph(child, document).text
        elif child.tag.endswith("}tbl"):
            table = Table(child, document)
            for row in table.rows:
                for cell in row.cells:
                    for paragraph in cell.paragraphs:
                        index += 1
                        yield index, paragraph.text


def _parse_docx(path: Path) -> ParseResult:
    try:
        from docx import Document

        document = Document(path)
    except ImportError as error:
        raise ResumeParseError("parser_unavailable", "DOCX 解析组件尚未安装") from error
    except Exception as error:
        raise ResumeParseError("invalid_docx", "DOCX 文件损坏或无法读取") from error

    segments: list[ParsedSegment] = []
    for paragraph_index, raw_text in _iter_docx_paragraph_text(document):
        normalized_text = normalize_resume_text(raw_text)
        if normalized_text:
            segments.append(
                ParsedSegment(
                    source_type="docx_paragraph",
                    source_index=paragraph_index,
                    paragraph_index=paragraph_index,
                    raw_text=raw_text,
                    normalized_text=normalized_text,
                )
            )
    if not segments:
        raise ResumeParseError("empty_text", "DOCX 未包含可解析文本")
    return ParseResult(extraction_method="docx_text", segments=segments)


def _parse_image(path: Path, *, ocr_engine: OCREngine | None) -> ParseResult:
    try:
        image_bytes = path.read_bytes()
    except OSError as error:
        raise ResumeParseError("file_unavailable", "原始图片无法读取") from error
    segment = _ocr_segment(
        image_bytes,
        engine=ocr_engine or get_ocr_engine(),
        source_type="image_ocr",
        source_index=1,
    )
    if segment is None:
        raise ResumeParseError("empty_text", "图片 OCR 未识别到有效文本")
    return ParseResult(extraction_method="image_ocr", segments=[segment])


def parse_resume_file(
    path: Path,
    detected_type: str,
    *,
    ocr_engine: OCREngine | None = None,
    min_pdf_text_characters: int = 80,
    pdf_render_scale: float = 2.0,
) -> ParseResult:
    if detected_type == "pdf":
        return _parse_pdf(
            path,
            ocr_engine=ocr_engine,
            min_text_characters=min_pdf_text_characters,
            render_scale=pdf_render_scale,
        )
    if detected_type == "docx":
        return _parse_docx(path)
    if detected_type in {"jpg", "png"}:
        return _parse_image(path, ocr_engine=ocr_engine)
    raise ResumeParseError("unsupported_type", "该文件类型不支持文本解析")
