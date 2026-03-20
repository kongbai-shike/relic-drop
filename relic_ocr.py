import re
import tempfile
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from relic_ev import normalize_relic_name


@dataclass
class OCRRelicHit:
    name: str
    count: int
    max_conf: float
    raw_texts: List[str] = field(default_factory=list)


@dataclass
class _OCRDetection:
    text: str
    conf: float
    center: Tuple[float, float]
    inline_count: Optional[int]


def _normalize_ocr_line(s: str) -> str:
    s = s.strip().replace("\u3000", " ")
    s = s.replace("[", " ").replace("]", " ")
    s = s.replace("（", "(").replace("）", ")")
    s = re.sub(r"\s+", " ", s)
    return s


def _extract_candidates_from_text(text: str) -> List[str]:
    text = _normalize_ocr_line(text)

    # Remove refinement hints like [光辉], [Radiant]
    text = re.sub(r"\[[^\]]+\]", " ", text)
    text = re.sub(r"\((?:intact|exceptional|flawless|radiant|完好|优良|无暇|辉耀|光辉)\)", " ", text, flags=re.IGNORECASE)

    pattern = re.compile(
        r"(古纪|前纪|中纪|后纪|安魂|赤毒|Lith|Meso|Neo|Axi|Requiem)\s*([A-Za-z0-9]{1,4})",
        flags=re.IGNORECASE,
    )

    out: List[str] = []
    for m in pattern.finditer(text):
        era = m.group(1)
        code = m.group(2)
        raw_name = f"{era} {code}"
        try:
            out.append(normalize_relic_name(raw_name))
        except Exception:
            continue

    return out


def _extract_inline_count(text: str) -> Optional[int]:
    m = re.search(r"[xX×]\s*(\d{1,2})", text)
    if not m:
        return None
    try:
        n = int(m.group(1))
    except Exception:
        return None
    return n if n > 0 else None


def _extract_qty_only(text: str) -> Optional[int]:
    m = re.fullmatch(r"\s*[xX×]\s*(\d{1,2})\s*", text)
    if not m:
        return None
    n = int(m.group(1))
    return n if n > 0 else None


def _bbox_center(box: Any) -> Tuple[float, float]:
    if not isinstance(box, (list, tuple)) or not box:
        return 0.0, 0.0
    xs: List[float] = []
    ys: List[float] = []
    for p in box:
        if isinstance(p, (list, tuple)) and len(p) >= 2:
            try:
                xs.append(float(p[0]))
                ys.append(float(p[1]))
            except Exception:
                continue
    if not xs or not ys:
        return 0.0, 0.0
    return sum(xs) / len(xs), sum(ys) / len(ys)


def _parse_ocr_result_rows(result: Any) -> List[_OCRDetection]:
    detections: List[_OCRDetection] = []
    if not isinstance(result, list):
        return detections

    for row in result:
        if not isinstance(row, (list, tuple)) or len(row) < 2:
            continue
        box = row[0]
        text = row[1]
        if not isinstance(text, str):
            continue

        conf = 1.0
        if len(row) >= 3 and isinstance(row[2], (float, int)):
            conf = float(row[2])

        detections.append(_OCRDetection(
            text=text,
            conf=conf,
            center=_bbox_center(box),
            inline_count=_extract_inline_count(text),
        ))

    return detections


def _assign_count_from_nearby_qty(
    relic_center: Tuple[float, float],
    qty_dets: List[_OCRDetection],
    used_idx: set,
) -> Optional[int]:
    rx, ry = relic_center
    best_idx = -1
    best_dist = 1e18

    for i, q in enumerate(qty_dets):
        if i in used_idx:
            continue
        qv = _extract_qty_only(q.text)
        if qv is None:
            continue

        qx, qy = q.center
        if qy > ry:
            continue
        if ry - qy > 260:
            continue
        if abs(rx - qx) > 260:
            continue

        dist = (rx - qx) ** 2 + (ry - qy) ** 2
        if dist < best_dist:
            best_dist = dist
            best_idx = i

    if best_idx < 0:
        return None

    used_idx.add(best_idx)
    return _extract_qty_only(qty_dets[best_idx].text)


def extract_relic_hits_from_image(
    image_path: str,
    min_confidence: float = 0.45,
    debug: bool = False,
) -> List[OCRRelicHit]:
    return _extract_relic_hits_impl(image_path, min_confidence=min_confidence, debug=debug)


def _extract_relic_hits_impl(
    image_input: Any,
    min_confidence: float = 0.45,
    debug: bool = False,
) -> List[OCRRelicHit]:
    try:
        from rapidocr_onnxruntime import RapidOCR
    except Exception as e:
        raise RuntimeError(
            "缺少 OCR 依赖 rapidocr-onnxruntime，请先执行: python -m pip install rapidocr-onnxruntime pillow"
        ) from e

    engine = RapidOCR()
    result, _ = engine(image_input)
    if not result:
        return []

    dets = _parse_ocr_result_rows(result)
    qty_dets = [d for d in dets if _extract_qty_only(d.text) is not None and d.conf >= min_confidence]
    used_qty_idx: set = set()

    merged: Dict[str, OCRRelicHit] = {}
    for d in dets:
        if d.conf < min_confidence:
            continue
        names = _extract_candidates_from_text(d.text)
        if not names:
            continue

        for name in names:
            cnt = d.inline_count if d.inline_count is not None else _assign_count_from_nearby_qty(d.center, qty_dets, used_qty_idx)
            if cnt is None:
                cnt = 1

            prev = merged.get(name)
            if prev is None:
                merged[name] = OCRRelicHit(name=name, count=cnt, max_conf=d.conf, raw_texts=[d.text])
            else:
                prev.count += cnt
                prev.max_conf = max(prev.max_conf, d.conf)
                if d.text not in prev.raw_texts:
                    prev.raw_texts.append(d.text)

    out = list(merged.values())
    out.sort(key=lambda x: x.name)

    if debug:
        debug_rows = [f"{x.name} x{x.count} (conf={x.max_conf:.2f})" for x in out]
        print(f"[DEBUG] OCR relic hits: {debug_rows}")

    return out


def extract_relic_hits_from_clipboard(
    min_confidence: float = 0.45,
    debug: bool = False,
) -> List[OCRRelicHit]:
    try:
        from PIL import Image, ImageGrab
    except Exception as e:
        raise RuntimeError("缺少 Pillow 依赖，请先执行: python -m pip install pillow") from e

    clip = ImageGrab.grabclipboard()
    if clip is None:
        raise RuntimeError("剪贴板中没有图片")

    if isinstance(clip, Image.Image):
        # RapidOCR accepts file paths; save clipboard image to a temp file first.
        with tempfile.NamedTemporaryFile(suffix=".png", delete=True) as tmp:
            clip.save(tmp.name, format="PNG")
            return _extract_relic_hits_impl(tmp.name, min_confidence=min_confidence, debug=debug)

    if isinstance(clip, list):
        image_files = [
            str(p)
            for p in clip
            if isinstance(p, str) and str(p).lower().endswith((".png", ".jpg", ".jpeg", ".bmp", ".webp"))
        ]
        if not image_files:
            raise RuntimeError("剪贴板内容不是图片")
        return _extract_relic_hits_impl(image_files[0], min_confidence=min_confidence, debug=debug)

    raise RuntimeError("当前平台或剪贴板格式暂不支持图片识别")


def extract_relic_names_from_image(image_path: str, debug: bool = False) -> List[str]:
    """Compatibility API: OCR image and return deduplicated normalized names."""
    hits = extract_relic_hits_from_image(image_path, debug=debug)
    return [x.name for x in hits]

