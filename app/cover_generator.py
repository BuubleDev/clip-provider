import hashlib
import json
import re
from datetime import datetime
from pathlib import Path

FALLBACK_TITLES = [
    "EASY HAIR TUTORIAL",
    "SAVE THIS HAIR IDEA",
    "QUICK EVERYDAY HAIRSTYLE",
    "SIMPLE HAIR TUTORIAL",
    "EASY UPDO IDEA",
    "HAIR IDEA TO TRY",
    "QUICK HAIR TRANSFORMATION",
    "EASY EVERYDAY UPDO",
    "SIMPLE STYLE IN SECONDS",
    "YOUR NEXT HAIR IDEA",
]

STYLE_TITLES = {
    "half-up": [
        "EASY HALF-UP STYLE", "QUICK HALF-UP HAIR",
        "HALF-UP CLAW CLIP", "EVERYDAY HALF-UP IDEA",
        "SAVE THIS HALF-UP STYLE", "SIMPLE HALF-UP TUTORIAL",
        "HALF-UP HAIR IN SECONDS", "EFFORTLESS HALF-UP HAIR",
    ],
    "bun": [
        "QUICK CLAW CLIP BUN", "SIMPLE LOW BUN",
        "EASY EVERYDAY BUN", "SAVE THIS BUN IDEA",
        "EASY CLAW CLIP UPDO", "NO-FUSS HAIR BUN",
        "SECURE CLAW CLIP BUN", "EFFORTLESS BUN TUTORIAL",
        "QUICK UPDO WITH A CLIP", "EVERYDAY CLAW CLIP BUN",
    ],
    "ponytail": [
        "EASY CLAW CLIP PONYTAIL", "QUICK PONYTAIL IDEA",
        "EVERYDAY PONYTAIL STYLE", "SAVE THIS PONYTAIL",
        "SIMPLE PONYTAIL TUTORIAL", "CLAW CLIP PONYTAIL HACK",
    ],
    "twist": [
        "EASY FRENCH TWIST", "QUICK TWISTED UPDO",
        "SIMPLE CLAW CLIP TWIST", "SAVE THIS FRENCH TWIST",
        "EVERYDAY TWIST TUTORIAL", "EFFORTLESS HAIR TWIST",
    ],
    "hairpin": [
        "EASY HAIR PIN STYLE", "QUICK HAIR PIN UPDO",
        "SIMPLE HAIR PIN TUTORIAL", "EVERYDAY HAIR PIN IDEA",
        "SAVE THIS HAIR PIN STYLE", "EASY UPDO WITH A PIN",
    ],
    "claw-clip": [
        "EASY CLAW CLIP STYLE", "QUICK CLAW CLIP HAIR",
        "SIMPLE CLAW CLIP TUTORIAL", "EVERYDAY CLAW CLIP IDEA",
        "SAVE THIS CLAW CLIP STYLE", "EASY HAIR WITH A CLAW CLIP",
        "CLAW CLIP STYLE TO TRY", "QUICK EVERYDAY CLAW CLIP",
        "NO-FUSS CLAW CLIP HAIR", "EFFORTLESS CLAW CLIP UPDO",
    ],
}


def _style_key(text):
    normalized = re.sub(r"[^a-z0-9]+", "-", text.lower())
    if "half-up" in normalized or "halfup" in normalized:
        return "half-up"
    if "ponytail" in normalized:
        return "ponytail"
    if "french" in normalized or "twist" in normalized:
        return "twist"
    if "hair-pin" in normalized or "hairpin" in normalized:
        return "hairpin"
    if "bun" in normalized or "updo" in normalized:
        return "bun"
    if "claw" in normalized or "clip" in normalized:
        return "claw-clip"
    return ""


def _read_history(history_path):
    history_path = Path(history_path)
    if not history_path.exists():
        return []
    try:
        data = json.loads(history_path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def choose_cover_title(source, metadata=None, history_path=None, duration_seconds=None):
    source = Path(source)
    metadata = metadata if isinstance(metadata, dict) else {}
    searchable = " ".join(str(value or "") for value in (
        source.stem, metadata.get("category"), metadata.get("style"),
        metadata.get("keyword"), metadata.get("title"),
    ))
    style = _style_key(searchable)
    candidates = list(STYLE_TITLES.get(style, []))
    if duration_seconds and duration_seconds <= 30:
        candidates.extend([
            "30-SECOND HAIR IDEA",
            "QUICK STYLE IN SECONDS",
            "FAST EVERYDAY HAIR",
        ])
    candidates.extend(FALLBACK_TITLES)
    candidates = list(dict.fromkeys(candidates))

    history = _read_history(history_path) if history_path else []
    recent = {
        str(item.get("title", "") if isinstance(item, dict) else item).upper()
        for item in history[-20:]
    }
    seed = int(hashlib.sha256(source.stem.encode("utf-8")).hexdigest()[:12], 16)
    rotated = candidates[seed % len(candidates):] + candidates[:seed % len(candidates)]
    title = next((value for value in rotated if value.upper() not in recent), rotated[0])

    if history_path:
        history.append({
            "file": source.name,
            "title": title,
            "style": style or "generic",
            "created_at": datetime.now().isoformat(timespec="seconds"),
        })
        Path(history_path).write_text(
            json.dumps(history[-500:], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    return title


def _best_frame(source):
    import cv2

    capture = cv2.VideoCapture(str(source))
    if not capture.isOpened():
        raise RuntimeError(f"Cannot open video for cover: {source}")
    fps = capture.get(cv2.CAP_PROP_FPS) or 30.0
    total = int(capture.get(cv2.CAP_PROP_FRAME_COUNT)) or 1
    duration = total / fps
    best = None
    best_score = float("-inf")
    for ratio in (0.58, 0.68, 0.78, 0.88):
        capture.set(cv2.CAP_PROP_POS_FRAMES, min(total - 1, max(0, round(total * ratio))))
        ok, frame = capture.read()
        if not ok:
            continue
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        h, w = gray.shape
        focus = gray[int(h * 0.12):int(h * 0.90), int(w * 0.08):int(w * 0.92)]
        sharpness = float(cv2.Laplacian(focus, cv2.CV_64F).var())
        score = sharpness + ratio * 8.0
        if score > best_score:
            best_score = score
            best = frame
    capture.release()
    if best is None:
        raise RuntimeError(f"Could not select a cover frame: {source}")
    return best, duration


def _crop_vertical(frame):
    import cv2

    height, width = frame.shape[:2]
    target_ratio = 9 / 16
    if width / height > target_ratio:
        crop_width = round(height * target_ratio)
        x = max(0, (width - crop_width) // 2)
        frame = frame[:, x:x + crop_width]
    elif width / height < target_ratio:
        crop_height = round(width / target_ratio)
        y = max(0, (height - crop_height) // 2)
        frame = frame[y:y + crop_height, :]
    frame = cv2.resize(frame, (1080, 1920), interpolation=cv2.INTER_LANCZOS4)
    blur = cv2.GaussianBlur(frame, (0, 0), 0.8)
    return cv2.addWeighted(frame, 1.55, blur, -0.55, 0)


def _split_title(draw, title, font, max_width=720):
    words = title.split()
    if not words:
        return ["EASY HAIR TUTORIAL"]
    lines = [words[0]]
    for word in words[1:]:
        candidate = f"{lines[-1]} {word}"
        if draw.textbbox((0, 0), candidate, font=font)[2] <= max_width or len(lines) == 2:
            lines[-1] = candidate
        else:
            lines.append(word)
    if len(lines) > 2:
        lines = [lines[0], " ".join(lines[1:])]
    return lines[:2]


def generate_cover(source, destination, metadata=None, history_path=None, headline=None):
    import cv2
    from PIL import Image, ImageDraw, ImageFont

    source = Path(source)
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    frame, duration = _best_frame(source)
    frame = _crop_vertical(frame)
    image = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
    draw = ImageDraw.Draw(image)
    font_path = Path(r"C:\Windows\Fonts\segoeuib.ttf")
    if not font_path.exists():
        font_path = Path(r"C:\Windows\Fonts\arialbd.ttf")
    font = ImageFont.truetype(str(font_path), 52)
    title = (headline or choose_cover_title(
        source, metadata=metadata, history_path=history_path,
        duration_seconds=duration,
    )).strip().upper()
    lines = _split_title(draw, title, font)

    x, y = 62, 105
    line_height = 66
    for index, line in enumerate(lines):
        at = (x, y + index * line_height)
        draw.text((at[0] + 2, at[1] + 2), line, font=font, fill=(25, 20, 20, 120))
        draw.text(at, line, font=font, fill=(255, 255, 255, 255),
                  stroke_width=1, stroke_fill=(70, 55, 55, 150))
    rule_y = y + len(lines) * line_height + 14
    draw.rounded_rectangle((x, rule_y, x + 144, rule_y + 8), radius=4,
                           fill=(216, 162, 173, 255))
    image.save(destination, quality=95, optimize=True)
    return {
        "path": str(destination),
        "headline": title,
        "duration_seconds": round(duration, 3),
        "width": 1080,
        "height": 1920,
        "generator": "local-template-no-ai",
    }
