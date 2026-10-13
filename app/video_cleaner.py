import shutil
import subprocess
import tempfile
import re
from pathlib import Path

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _ffmpeg_path():
    candidates = [
        shutil.which("ffmpeg"),
    ]
    return next((str(path) for path in candidates if path and Path(path).exists()), None)


def _ffprobe_path():
    ffmpeg = _ffmpeg_path()
    candidates = [
        shutil.which("ffprobe"),
        str(Path(ffmpeg).with_name("ffprobe.exe")) if ffmpeg else None,
    ]
    return next((str(path) for path in candidates if path and Path(path).exists()), None)


def _media_duration(source):
    ffprobe = _ffprobe_path()
    if not ffprobe:
        raise RuntimeError("FFprobe was not found")
    completed = subprocess.run(
        [ffprobe, "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nokey=1:noprint_wrappers=1", str(source)],
        capture_output=True, text=True, timeout=60, creationflags=NO_WINDOW,
    )
    if completed.returncode != 0:
        raise RuntimeError((completed.stderr or "Could not read video duration").strip())
    return float(completed.stdout.strip())


def add_music_to_video(source, destination, music, volume=0.24):
    """Create a fast StockOS copy with a looped music track and no source audio.

    The reviewed Ready file is never changed. Video is stream-copied, so this
    final step is quick; only the new AAC audio track is encoded.
    """
    source = Path(source)
    destination = Path(destination)
    music = Path(music)
    if not source.is_file():
        raise FileNotFoundError(f"Video was not found: {source}")
    if not music.is_file():
        raise FileNotFoundError(f"Music was not found: {music}")
    ffmpeg = _ffmpeg_path()
    if not ffmpeg:
        raise RuntimeError("FFmpeg was not found")
    duration = _media_duration(source)
    if duration <= 0:
        raise RuntimeError("Video duration is invalid")
    destination.parent.mkdir(parents=True, exist_ok=True)
    fade_out = max(0.1, duration - 0.55)
    audio_filter = (
        f"[1:a:0]atrim=0:{duration:.3f},asetpts=PTS-STARTPTS,"
        f"volume={max(0.0, min(float(volume), 1.0)):.3f},"
        "afade=t=in:st=0:d=0.20,"
        f"afade=t=out:st={fade_out:.3f}:d=0.50[a]"
    )
    command = [
        ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(source), "-stream_loop", "-1", "-i", str(music),
        "-filter_complex", audio_filter,
        "-map", "0:v:0", "-map", "[a]", "-map_metadata", "0",
        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest",
        "-movflags", "+faststart", str(destination),
    ]
    completed = subprocess.run(
        command, capture_output=True, text=True, timeout=3600,
        creationflags=NO_WINDOW,
    )
    if completed.returncode != 0 or not destination.exists():
        destination.unlink(missing_ok=True)
        raise RuntimeError((completed.stderr or "Music mix failed").strip().splitlines()[-1])
    return destination


def mute_video_in_place(source):
    """Remove every audio stream without re-encoding video, replacing the source safely."""
    source = Path(source)
    ffmpeg = _ffmpeg_path()
    if not ffmpeg:
        raise RuntimeError("FFmpeg was not found")
    temporary = source.with_name(f".{source.stem}.muting{source.suffix}")
    command = [
        ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(source), "-map", "0:v:0", "-map_metadata", "0",
        "-c:v", "copy", "-an",
    ]
    if source.suffix.lower() in (".mp4", ".mov", ".m4v"):
        command += ["-movflags", "+faststart"]
    command.append(str(temporary))
    completed = subprocess.run(command, capture_output=True, text=True, timeout=3600,
                               creationflags=NO_WINDOW)
    if completed.returncode != 0 or not temporary.exists():
        temporary.unlink(missing_ok=True)
        raise RuntimeError((completed.stderr or "Audio removal failed").strip().splitlines()[-1])
    temporary.replace(source)
    return source


def brand_video(source, destination, brand="BUUBLE.VBG | Hair Ideas",
                website="buublestore.com", position="top-left", mute_audio=False):
    """Fast, non-destructive branding that preserves the original picture and audio."""
    import cv2
    from PIL import Image, ImageDraw, ImageFont

    source = Path(source)
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    capture = cv2.VideoCapture(str(source))
    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    capture.release()
    if width <= 0 or height <= 0:
        raise RuntimeError(f"Cannot read video dimensions: {source}")

    scale = max(1, round(width / 720))
    font_size = max(22, round(width * 0.038))
    small_size = max(16, round(font_size * 0.68))
    font_path = Path(r"C:\Windows\Fonts\arialbd.ttf")
    regular_path = Path(r"C:\Windows\Fonts\arial.ttf")
    font = ImageFont.truetype(str(font_path if font_path.exists() else regular_path), font_size)
    small = ImageFont.truetype(str(regular_path), small_size)
    overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    brand = brand.strip() or "BUUBLE.VBG"
    website = website.strip()
    b1 = draw.textbbox((0, 0), brand, font=font)
    b2 = draw.textbbox((0, 0), website, font=small) if website else (0, 0, 0, 0)
    panel_w = max(b1[2], b2[2]) + 32 * scale
    panel_h = (b1[3] - b1[1]) + (b2[3] - b2[1] if website else 0) + 34 * scale
    margin = 18 * scale
    x = margin if "left" in position else width - panel_w - margin
    y = margin if "top" in position else height - panel_h - margin
    radius = 12 * scale
    draw.rounded_rectangle((x, y, x + panel_w, y + panel_h), radius=radius,
                           fill=(12, 12, 12, 128), outline=(255, 255, 255, 70), width=max(1, scale))
    tx = x + 16 * scale
    ty = y + 9 * scale
    draw.text((tx, ty), brand, font=font, fill=(255, 255, 255, 245))
    if website:
        draw.text((tx, ty + (b1[3] - b1[1]) + 6 * scale), website,
                  font=small, fill=(235, 235, 235, 235))

    ffmpeg = _ffmpeg_path()
    if not ffmpeg:
        raise RuntimeError("FFmpeg was not found")
    with tempfile.TemporaryDirectory(prefix="buuble_brand_") as temp_dir:
        png = Path(temp_dir) / "overlay.png"
        overlay.save(png)
        command = [
            ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
            "-i", str(source), "-i", str(png),
            "-filter_complex", "[0:v][1:v]overlay=0:0:format=auto[v]",
            "-map", "[v]",
        ]
        if not mute_audio:
            command += ["-map", "0:a?"]
        command += ["-map_metadata", "0", "-c:v", "libx264", "-preset", "fast", "-crf", "18"]
        if not mute_audio:
            command += ["-c:a", "copy"]
        command += ["-movflags", "+faststart", str(destination)]
        completed = subprocess.run(command, capture_output=True, text=True, timeout=7200,
                                   creationflags=NO_WINDOW)
        if completed.returncode != 0:
            raise RuntimeError((completed.stderr or "Branding failed").strip().splitlines()[-1])
    return destination


def clean_video(source, destination, brand="BUUBLE.VBG | Hair Ideas",
                website="buublestore.com", progress=None, detections_per_second=10,
                position="bottom-right", mute_audio=False, headline="",
                headline_vertical_position=0.43):
    """Create a branded copy, removing OCR-detected text with temporal masks."""
    import cv2
    import numpy as np
    from rapidocr import RapidOCR

    source = Path(source)
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    silent = destination.with_name(f".{destination.stem}.silent.mp4")

    capture = cv2.VideoCapture(str(source))
    if not capture.isOpened():
        raise RuntimeError(f"Cannot open video: {source}")
    fps = capture.get(cv2.CAP_PROP_FPS) or 30.0
    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total = int(capture.get(cv2.CAP_PROP_FRAME_COUNT)) or 1
    interval = max(1, round(fps / max(1, detections_per_second)))
    ocr = RapidOCR()
    detect_width = min(width, 640)
    scale = detect_width / width
    sampled_boxes = {}
    frame_no = 0
    # Pass 1: detect text ahead of processing so masks can cover frames just
    # before and after an animated caption appears.
    try:
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            if frame_no % interval == 0:
                small = cv2.resize(frame, (detect_width, max(1, round(height * scale))))
                result = ocr(small)
                rectangles = []
                boxes = getattr(result, "boxes", None)
                if boxes is not None:
                    for box in boxes:
                        points = np.asarray(box, dtype=np.float32) / scale
                        x1 = max(0, int(points[:, 0].min()) - 12)
                        y1 = max(0, int(points[:, 1].min()) - 10)
                        x2 = min(width - 1, int(points[:, 0].max()) + 12)
                        y2 = min(height - 1, int(points[:, 1].max()) + 10)
                        rectangles.append((x1, y1, x2, y2))
                sampled_boxes[frame_no] = rectangles
            frame_no += 1
            if progress and (frame_no % max(1, round(fps)) == 0 or frame_no == total):
                progress(frame_no, total * 2)
    finally:
        capture.release()

    capture = cv2.VideoCapture(str(source))
    writer = cv2.VideoWriter(str(silent), cv2.VideoWriter_fourcc(*"mp4v"), fps, (width, height))
    if not writer.isOpened():
        capture.release()
        raise RuntimeError("Cannot create temporary processed video")
    mask = np.zeros((height, width), dtype=np.uint8)
    frame_no = 0
    headline = str(headline or "").strip()
    headline_font = cv2.FONT_HERSHEY_SIMPLEX
    if headline:
        headline_scale = max(0.55, width / 900)
        (headline_w, headline_h), _ = cv2.getTextSize(
            headline, headline_font, headline_scale, 2
        )
        headline_max_width = round(width * 0.88)
        headline_scale = min(
            headline_scale,
            headline_scale * headline_max_width / max(1, headline_w),
        )
        headline_thickness = max(1, round(headline_scale * 2))
        (headline_w, headline_h), _ = cv2.getTextSize(
            headline, headline_font, headline_scale, headline_thickness
        )
        headline_x = max(12, (width - headline_w) // 2)
        headline_y = max(
            headline_h + 12,
            min(height - 12, round(height * headline_vertical_position)),
        )
    try:
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            before = (frame_no // interval) * interval
            after = min(((frame_no + interval - 1) // interval) * interval,
                        max(sampled_boxes.keys(), default=before))
            mask.fill(0)
            for rect in sampled_boxes.get(before, []) + sampled_boxes.get(after, []):
                cv2.rectangle(mask, (rect[0], rect[1]), (rect[2], rect[3]), 255, -1)
            if mask.any():
                kernel = np.ones((7, 7), np.uint8)
                mask = cv2.dilate(mask, kernel, iterations=1)

            cleaned = cv2.inpaint(frame, mask, 5, cv2.INPAINT_TELEA) if mask.any() else frame.copy()

            # Keep branding discreet.  The old opaque panel obscured too much
            # of a vertical Reel and could be mistaken for another caption.
            font = cv2.FONT_HERSHEY_SIMPLEX
            font_scale = max(0.40, width / 1800)
            thickness = max(1, round(width / 1080))
            label = " | ".join(value for value in (
                brand.strip() or "BUUBLE.VBG", website.strip()
            ) if value)
            (label_w, label_h), baseline = cv2.getTextSize(label, font, font_scale, thickness)
            margin = max(14, round(width * 0.025))
            x = margin if "left" in position else max(margin, width - label_w - margin)
            y = margin + label_h if "top" in position else max(label_h + margin, height - margin - baseline)
            # A narrow outline keeps the watermark readable without a box.
            cv2.putText(cleaned, label, (x, y), font, font_scale,
                        (24, 24, 24), thickness + 2, cv2.LINE_AA)
            cv2.putText(cleaned, label, (x, y), font, font_scale,
                        (245, 245, 245), thickness, cv2.LINE_AA)
            if headline:
                cv2.putText(
                    cleaned, headline, (headline_x, headline_y), headline_font,
                    headline_scale, (8, 8, 8),
                    headline_thickness + max(3, round(width / 220)), cv2.LINE_AA,
                )
                cv2.putText(
                    cleaned, headline, (headline_x, headline_y), headline_font,
                    headline_scale, (255, 255, 255), headline_thickness, cv2.LINE_AA,
                )
            writer.write(cleaned)
            frame_no += 1
            if progress and (frame_no % max(1, round(fps)) == 0 or frame_no == total):
                progress(total + frame_no, total * 2)
    finally:
        capture.release()
        writer.release()

    ffmpeg = _ffmpeg_path()
    if not ffmpeg:
        silent.replace(destination)
        return destination
    command = [
        ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(silent), "-i", str(source),
        "-map", "0:v:0",
    ]
    if not mute_audio:
        command += ["-map", "1:a?"]
    command += ["-map_metadata", "1", "-c:v", "libx264", "-preset", "medium", "-crf", "18"]
    if not mute_audio:
        command += ["-c:a", "aac", "-b:a", "192k"]
    command += ["-movflags", "+faststart", str(destination)]
    completed = subprocess.run(command, capture_output=True, text=True, timeout=7200,
                               creationflags=NO_WINDOW)
    if completed.returncode != 0:
        raise RuntimeError((completed.stderr or "ffmpeg audio merge failed").strip().splitlines()[-1])
    silent.unlink(missing_ok=True)
    return destination


def clean_english_text_video(source, destination, headline="Easy Hair Tutorial",
                             brand="BUUBLE.VBG", website="buublestore.com",
                             progress=None, detections_per_second=10,
                             position="bottom-right", mute_audio=True):
    """Remove detected source text first, then add one English headline."""
    return clean_video(
        source, destination, brand=brand, website=website, progress=progress,
        detections_per_second=detections_per_second, position=position,
        mute_audio=mute_audio, headline=headline,
    )


def _merge_rectangles(rectangles, width, height, gap=20):
    merged = [list(rect) for rect in rectangles]
    changed = True
    while changed:
        changed = False
        output = []
        while merged:
            current = merged.pop(0)
            index = 0
            while index < len(merged):
                other = merged[index]
                separated = (current[2] + gap < other[0] or other[2] + gap < current[0]
                             or current[3] + gap < other[1] or other[3] + gap < current[1])
                if separated:
                    index += 1
                    continue
                current = [min(current[0], other[0]), min(current[1], other[1]),
                           max(current[2], other[2]), max(current[3], other[3])]
                merged.pop(index)
                changed = True
            output.append(current)
        merged = output
    return [(max(0, x1), max(0, y1), min(width - 1, x2), min(height - 1, y2))
            for x1, y1, x2, y2 in merged]


def cover_text_video(source, destination, headline="Easy Claw Clip Tutorial",
                     brand="BUUBLE.VBG", website="buublestore.com", progress=None,
                     detections_per_second=8, mute_audio=True, use_panels=True):
    """Cover OCR text with intentional English design panels instead of inpainting."""
    import cv2
    import numpy as np
    from rapidocr import RapidOCR

    source = Path(source)
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    silent = destination.with_name(f".{destination.stem}.silent.mp4")
    capture = cv2.VideoCapture(str(source))
    if not capture.isOpened():
        raise RuntimeError(f"Cannot open video: {source}")
    fps = capture.get(cv2.CAP_PROP_FPS) or 30.0
    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total = int(capture.get(cv2.CAP_PROP_FRAME_COUNT)) or 1
    interval = max(1, round(fps / max(1, detections_per_second)))
    detect_width = min(width, 720)
    scale = detect_width / width
    ocr = RapidOCR()
    sampled_boxes = {}
    frame_no = 0
    try:
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            if frame_no % interval == 0:
                small = cv2.resize(frame, (detect_width, max(1, round(height * scale))))
                result = ocr(small)
                rectangles = []
                boxes = getattr(result, "boxes", None)
                if boxes is not None:
                    for box in boxes:
                        points = np.asarray(box, dtype=np.float32) / scale
                        x1 = max(0, int(points[:, 0].min()) - 14)
                        y1 = max(0, int(points[:, 1].min()) - 12)
                        x2 = min(width - 1, int(points[:, 0].max()) + 14)
                        y2 = min(height - 1, int(points[:, 1].max()) + 12)
                        rectangles.append((x1, y1, x2, y2))
                sampled_boxes[frame_no] = rectangles
            frame_no += 1
            if progress and (frame_no % max(1, round(fps)) == 0 or frame_no == total):
                progress(frame_no, total * 2)
    finally:
        capture.release()

    capture = cv2.VideoCapture(str(source))
    writer = cv2.VideoWriter(str(silent), cv2.VideoWriter_fourcc(*"mp4v"), fps, (width, height))
    if not writer.isOpened():
        capture.release()
        raise RuntimeError("Cannot create temporary covered video")
    frame_no = 0
    font = cv2.FONT_HERSHEY_SIMPLEX
    try:
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            before = (frame_no // interval) * interval
            after = min(((frame_no + interval - 1) // interval) * interval,
                        max(sampled_boxes.keys(), default=before))
            rectangles = _merge_rectangles(
                sampled_boxes.get(before, []) + sampled_boxes.get(after, []), width, height,
                gap=max(12, round(width * 0.018)),
            )
            if rectangles and not use_panels:
                primary = max(rectangles, key=lambda rect: (rect[2] - rect[0]) * (rect[3] - rect[1]))
                x1, y1, x2, y2 = primary
                max_width = round(width * 0.82)
                base_scale = max(0.55, width / 900)
                (tw, th), _ = cv2.getTextSize(headline, font, base_scale, 2)
                text_scale = min(base_scale * max_width / max(1, tw), width / 720)
                text_scale = max(0.42, text_scale)
                thickness = max(1, round(text_scale * 2))
                (tw, th), _ = cv2.getTextSize(headline, font, text_scale, thickness)
                cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
                tx = max(12, min(width - tw - 12, cx - tw // 2))
                ty = max(th + 12, min(height - 12, cy + th // 2))
                cv2.putText(frame, headline, (tx, ty), font, text_scale,
                            (12, 12, 12), thickness + max(3, round(width / 240)), cv2.LINE_AA)
                cv2.putText(frame, headline, (tx, ty), font, text_scale,
                            (255, 255, 255), thickness, cv2.LINE_AA)
            elif rectangles:
                primary = max(rectangles, key=lambda rect: (rect[2] - rect[0]) * (rect[3] - rect[1]))
                px1, py1, px2, py2 = primary
                target_w = max(px2 - px1, round(width * 0.48))
                target_h = max(py2 - py1, round(height * 0.072))
                cx, cy = (px1 + px2) // 2, (py1 + py2) // 2
                px1 = max(8, min(width - target_w - 8, cx - target_w // 2))
                py1 = max(8, min(height - target_h - 8, cy - target_h // 2))
                primary_panel = (px1, py1, px1 + target_w, py1 + target_h)

                # Secondary text receives a quiet frosted patch. It does not repeat
                # the brand, which made the first prototype look cluttered.
                for rect in [value for value in rectangles if value != primary]:
                    x1, y1, x2, y2 = rect
                    roi = frame[y1:y2, x1:x2]
                    if roi.size:
                        kernel = max(9, (min(51, max(9, (min(roi.shape[:2]) // 3) | 1))))
                        blurred = cv2.GaussianBlur(roi, (kernel, kernel), 0)
                        tint = np.full_like(roi, (48, 42, 38))
                        panel = cv2.addWeighted(blurred, 0.06, tint, 0.94, 0)
                        frame[y1:y2, x1:x2] = panel

                x1, y1, x2, y2 = primary_panel
                roi = frame[y1:y2, x1:x2]
                if roi.size:
                    kernel = max(9, (min(51, max(9, (min(roi.shape[:2]) // 3) | 1))))
                    blurred = cv2.GaussianBlur(roi, (kernel, kernel), 0)
                    tint = np.full_like(roi, (28, 24, 22))
                    frame[y1:y2, x1:x2] = cv2.addWeighted(blurred, 0.04, tint, 0.96, 0)
                cv2.rectangle(frame, (x1, y1), (x2, y2), (214, 190, 165),
                              max(1, round(width / 720)))
                max_width = max(20, x2 - x1 - 24)
                max_height = max(16, y2 - y1 - 16)
                base_scale = max(0.35, width / 1000)
                (tw, th), _ = cv2.getTextSize(headline, font, base_scale, 2)
                text_scale = min(base_scale * max_width / max(1, tw),
                                 base_scale * max_height / max(1, th), width / 650)
                text_scale = max(0.24, text_scale)
                thickness = max(1, round(text_scale * 2))
                (tw, th), _ = cv2.getTextSize(headline, font, text_scale, thickness)
                tx = x1 + max(8, (x2 - x1 - tw) // 2)
                ty = y1 + max(th + 4, (y2 - y1 + th) // 2)
                cv2.putText(frame, headline, (tx, ty), font, text_scale,
                            (250, 247, 242), thickness, cv2.LINE_AA)

            small_scale = max(0.45, width / 1500)
            line = (brand.strip() or "BUUBLE.VBG") + (f"  |  {website.strip()}" if website.strip() else "")
            (tw, th), _ = cv2.getTextSize(line, font, small_scale, 1)
            bx, by = max(10, width - tw - 22), max(th + 10, height - 24)
            if use_panels:
                overlay = frame.copy()
                cv2.rectangle(overlay, (bx - 10, by - th - 7), (width - 8, by + 8), (0, 0, 0), -1)
                frame = cv2.addWeighted(overlay, 0.52, frame, 0.48, 0)
            else:
                cv2.putText(frame, line, (bx, by), font, small_scale,
                            (0, 0, 0), 4, cv2.LINE_AA)
            cv2.putText(frame, line, (bx, by), font, small_scale, (255, 255, 255), 1, cv2.LINE_AA)
            writer.write(frame)
            frame_no += 1
            if progress and (frame_no % max(1, round(fps)) == 0 or frame_no == total):
                progress(total + frame_no, total * 2)
    finally:
        capture.release()
        writer.release()

    ffmpeg = _ffmpeg_path()
    if not ffmpeg:
        silent.replace(destination)
        return destination
    command = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
               "-i", str(silent), "-i", str(source), "-map", "0:v:0"]
    if not mute_audio:
        command += ["-map", "1:a?"]
    command += ["-map_metadata", "1", "-c:v", "libx264", "-preset", "fast", "-crf", "18"]
    if not mute_audio:
        command += ["-c:a", "aac", "-b:a", "192k"]
    command += ["-movflags", "+faststart", str(destination)]
    completed = subprocess.run(command, capture_output=True, text=True, timeout=7200,
                               creationflags=NO_WINDOW)
    if completed.returncode != 0:
        raise RuntimeError((completed.stderr or "ffmpeg cover export failed").strip().splitlines()[-1])
    silent.unlink(missing_ok=True)
    return destination


def audit_unexpected_text(source, samples_per_second=4, ignored_terms=None, non_ascii_only=False):
    """Return OCR hits that remain after cleaning, excluding the BUUBLE overlay."""
    import cv2
    from rapidocr import RapidOCR

    ignored = tuple(x.lower() for x in (ignored_terms or (
        "buuble", "hair", "ideas", "hair ideas", "buublestore",
        "www.buublestore.com", "@buuble"
    )))
    source = Path(source)
    capture = cv2.VideoCapture(str(source))
    if not capture.isOpened():
        raise RuntimeError(f"Cannot audit video: {source}")
    fps = capture.get(cv2.CAP_PROP_FPS) or 30.0
    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH)) or 1
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT)) or 1
    interval = max(1, round(fps / max(1, samples_per_second)))
    detect_width = min(width, 720)
    detect_height = max(1, round(height * detect_width / width))
    ocr = RapidOCR()
    hits = []
    frame_no = 0
    try:
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            if frame_no % interval == 0:
                small = cv2.resize(frame, (detect_width, detect_height))
                result = ocr(small)
                texts = []
                values = getattr(result, "txts", None)
                if values is not None:
                    for value in values:
                        text = str(value).strip()
                        lowered = text.lower()
                        if non_ascii_only and not re.search(r"[^\x00-\x7f]", text):
                            continue
                        if len(text) >= 2 and not any(term in lowered for term in ignored):
                            texts.append(text)
                if texts:
                    hits.append({"time_seconds": round(frame_no / fps, 2), "texts": texts})
            frame_no += 1
    finally:
        capture.release()
    return hits


def scan_reuse_restrictions(source, samples_per_second=2, terms=None):
    """Find explicit no-repost/permission warnings before any OCR removal."""
    import cv2
    from rapidocr import RapidOCR

    restriction_terms = tuple(terms or (
        "不授权", "禁止搬运", "严禁搬运", "请勿搬运", "禁止转载", "请勿转载",
        "未经授权", "不得转载", "不可转载", "侵权必究", "do not repost",
        "no repost", "not authorized", "permission required",
    ))
    source = Path(source)
    capture = cv2.VideoCapture(str(source))
    if not capture.isOpened():
        raise RuntimeError(f"Cannot scan video rights text: {source}")
    fps = capture.get(cv2.CAP_PROP_FPS) or 30.0
    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH)) or 1
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT)) or 1
    interval = max(1, round(fps / max(1, samples_per_second)))
    detect_width = min(width, 720)
    detect_height = max(1, round(height * detect_width / width))
    ocr = RapidOCR()
    hits = []
    seen = set()
    frame_no = 0
    try:
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            if frame_no % interval == 0:
                result = ocr(cv2.resize(frame, (detect_width, detect_height)))
                values = getattr(result, "txts", None)
                if values is not None:
                    matched = []
                    for value in values:
                        text = str(value).strip()
                        lowered = text.lower()
                        if any(term.lower() in lowered for term in restriction_terms):
                            if text not in seen:
                                seen.add(text)
                                matched.append(text)
                    if matched:
                        hits.append({
                            "time_seconds": round(frame_no / fps, 2),
                            "texts": matched,
                        })
            frame_no += 1
    finally:
        capture.release()
    return hits
