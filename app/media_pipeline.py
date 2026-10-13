import json
import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


CATEGORY_RULES = [
    ("hair-claw", ("抓夹", "鲨鱼夹", "hair claw", "claw clip")),
    ("headband", ("发箍", "发带", "headband", "hair band")),
    ("earrings", ("耳环", "耳夹", "耳钉", "earring", "ear cuff")),
    ("nails", ("美甲", "指甲", "穿戴甲", "nail", "manicure")),
    ("skincare", ("粉刺", "黑头", "痘", "面膜", "护肤", "skincare", "acne")),
    ("makeup", ("化妆", "妆容", "眼影", "口红", "makeup")),
]

STYLE_RULES = [
    ("half-up", ("半扎", "half up", "half-up")),
    ("ponytail", ("马尾", "ponytail")),
    ("short-hair", ("短发", "short hair")),
    ("long-hair", ("长发", "long hair")),
    ("bun", ("丸子", "盘发", "发髻", "bun")),
    ("tutorial", ("教程", "用法", "tutorial", "how to")),
]


def _pick_rule(text, rules, fallback):
    lowered = text.lower()
    for label, terms in rules:
        if any(term.lower() in lowered for term in terms):
            return label
    return fallback


def classify(text, topic=""):
    combined = f"{text} {topic}"
    return (_pick_rule(combined, CATEGORY_RULES, "beauty"),
            _pick_rule(combined, STYLE_RULES, "general"))


def inspect_video(path):
    import cv2

    path = Path(path)
    capture = cv2.VideoCapture(str(path))
    if not capture.isOpened():
        raise RuntimeError(f"Cannot inspect {path}")
    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = capture.get(cv2.CAP_PROP_FPS) or 30.0
    frames = int(capture.get(cv2.CAP_PROP_FRAME_COUNT)) or 0
    duration = frames / fps if fps else 0
    sharpness_values, brightness_values, border_values = [], [], []
    sample_count = min(7, max(1, int(duration)))
    for index in range(sample_count):
        position = 0 if sample_count == 1 else index / (sample_count - 1)
        capture.set(cv2.CAP_PROP_POS_FRAMES, max(0, round((frames - 1) * position)))
        ok, frame = capture.read()
        if not ok:
            continue
        small_width = min(width, 480)
        small = cv2.resize(frame, (small_width, max(1, round(height * small_width / width))))
        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
        sharpness_values.append(float(cv2.Laplacian(gray, cv2.CV_64F).var()))
        brightness_values.append(float(gray.mean()))
        edge = max(2, round(min(gray.shape) * 0.025))
        strips = [gray[:edge, :], gray[-edge:, :], gray[:, :edge], gray[:, -edge:]]
        border_values.append(sum(float(strip.mean() < 12) for strip in strips) / 4)
    capture.release()
    short_edge = min(width, height)
    aspect = (width / height) if height else 0
    return {
        "width": width,
        "height": height,
        "resolution": f"{width}x{height}",
        "short_edge": short_edge,
        "fps": round(fps, 3),
        "duration_seconds": round(duration, 3),
        "aspect_ratio": round(aspect, 4),
        "vertical_9_16": bool(height >= width and abs(aspect - 9 / 16) <= 0.09),
        "average_sharpness": round(sum(sharpness_values) / len(sharpness_values), 2) if sharpness_values else None,
        "average_brightness": round(sum(brightness_values) / len(brightness_values), 2) if brightness_values else None,
        "black_border_score": round(sum(border_values) / len(border_values), 3) if border_values else None,
        "size_bytes": path.stat().st_size,
    }


def evaluate_video(info, minimum_short_edge=720, minimum_duration=8, maximum_duration=45):
    reasons = []
    status = "ready"
    if info["short_edge"] < minimum_short_edge:
        return "low-resolution", [f"short edge {info['short_edge']} < {minimum_short_edge}"]
    if info["duration_seconds"] < minimum_duration:
        return "too-short", [f"duration {info['duration_seconds']:.1f}s < {minimum_duration}s"]
    if info["duration_seconds"] > maximum_duration:
        return "needs-trim", [f"duration {info['duration_seconds']:.1f}s > {maximum_duration}s"]
    if not info["vertical_9_16"]:
        status = "needs-review"
        reasons.append("not close to vertical 9:16")
    if info["average_sharpness"] is not None and info["average_sharpness"] < 35:
        status = "needs-review"
        reasons.append("possibly blurry")
    if info["average_brightness"] is not None and info["average_brightness"] < 35:
        status = "needs-review"
        reasons.append("possibly too dark")
    if info["black_border_score"] is not None and info["black_border_score"] >= 0.5:
        status = "needs-review"
        reasons.append("large black border detected")
    return status, reasons


def video_id_from_url(url):
    patterns = (r"/video/(BV[0-9A-Za-z]+)", r"/video/(\d+)",
                r"/(?:explore|discovery/item|search_result)/([0-9a-f]{20,})")
    for pattern in patterns:
        match = re.search(pattern, url, re.I)
        if match:
            return match.group(1)
    return "unknown"


def platform_code(platform):
    return {"Douyin": "DY", "Xiaohongshu": "XHS", "Bilibili": "BILI"}.get(platform, "WEB")


def unique_path(path):
    path = Path(path)
    if not path.exists():
        return path
    index = 2
    while True:
        candidate = path.with_name(f"{path.stem}_{index}{path.suffix}")
        if not candidate.exists():
            return candidate
        index += 1


def duration_tag(seconds):
    """Return a compact, filesystem-friendly whole-second duration label."""
    try:
        rounded = max(1, int(float(seconds) + 0.5))
    except (TypeError, ValueError):
        rounded = 0
    return f"{rounded}s" if rounded else ""


def with_duration_in_name(path, seconds):
    """Add _18s to a media filename while avoiding duplicate duration tags."""
    path = Path(path)
    tag = duration_tag(seconds)
    if not tag or re.search(r"_\d+s(?:_|$)", path.stem, re.I):
        return path
    stem = path.stem
    resolution = re.search(r"_\d+x\d+(?=_|$)", stem, re.I)
    if resolution:
        stem = f"{stem[:resolution.start()]}_{tag}{stem[resolution.start():]}"
    else:
        marker = re.search(r"_(?:SRC|BUUBLE)(?=_|$)", stem, re.I)
        position = marker.start() if marker else len(stem)
        stem = f"{stem[:position]}_{tag}{stem[position:]}"
    return path.with_name(f"{stem}{path.suffix}")


def rename_source(path, platform, url, topic, info):
    path = Path(path)
    category, style = classify(path.stem, topic)
    video_id = video_id_from_url(url)
    length = duration_tag(info.get("duration_seconds"))
    length_part = f"_{length}" if length else ""
    name = f"{category}_{style}_{platform_code(platform)}_{video_id}{length_part}_{info['resolution']}_SRC{path.suffix.lower()}"
    destination = unique_path(path.with_name(name))
    if destination != path:
        path.rename(destination)
    return destination, category, style


def write_metadata(video_path, data):
    sidecar = Path(video_path).with_suffix(Path(video_path).suffix + ".json")
    sidecar.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return sidecar


def build_metadata(video_path, platform, url, topic, info, category, style, status, reasons):
    return {
        "downloaded_at": datetime.now().isoformat(timespec="seconds"),
        "platform": platform,
        "source_url": url,
        "source_video_id": video_id_from_url(url),
        "search_topic": topic,
        "category": category,
        "style": style,
        "usage_status": "reference_only_unless_permission_obtained",
        "pipeline_status": status,
        "review_reasons": reasons,
        "file": str(video_path),
        **info,
    }


def move_with_sidecar(video_path, directory):
    video_path = Path(video_path)
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    destination = unique_path(directory / video_path.name)
    shutil.move(str(video_path), str(destination))
    old_sidecar = video_path.with_suffix(video_path.suffix + ".json")
    if old_sidecar.exists():
        shutil.move(str(old_sidecar), str(destination.with_suffix(destination.suffix + ".json")))
    return destination


def has_audio(path, ffprobe):
    command = [str(ffprobe), "-v", "error", "-select_streams", "a:0",
               "-show_entries", "stream=codec_type", "-of", "csv=p=0", str(path)]
    result = subprocess.run(command, capture_output=True, text=True, timeout=60,
                            creationflags=NO_WINDOW)
    return bool(result.stdout.strip())
