#!/usr/bin/env python3
"""Automatically split a music compilation and create Reel-ready MP3 clips.

Requires FFmpeg and FFprobe on PATH. Uses only the Python standard library.
"""

from __future__ import annotations

import argparse
import array
import csv
import math
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg"}


@dataclass
class Track:
    number: int
    start: float
    end: float

    @property
    def duration(self) -> float:
        return self.end - self.start


def run(command: list[str], *, capture: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        command,
        check=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
        text=capture,
        encoding="utf-8",
        errors="replace",
    )


def locate_tools() -> tuple[str, str]:
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        raise RuntimeError("ไม่พบ FFmpeg/FFprobe กรุณาติดตั้งและเพิ่มลงใน PATH")
    return ffmpeg, ffprobe


def choose_input(folder: Path, requested: str | None) -> Path:
    if requested:
        result = Path(requested).expanduser().resolve()
        if not result.is_file():
            raise FileNotFoundError(f"ไม่พบไฟล์: {result}")
        return result

    files = [
        item
        for item in folder.iterdir()
        if item.is_file()
        and item.suffix.lower() in AUDIO_EXTENSIONS
        and not item.name.lower().startswith("reels-")
    ]
    if not files:
        raise FileNotFoundError("ไม่พบไฟล์เสียงในโฟลเดอร์นี้")
    return max(files, key=lambda item: item.stat().st_size)


def probe_duration(ffprobe: str, source: Path) -> float:
    result = run(
        [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=nokey=1:noprint_wrappers=1",
            str(source),
        ]
    )
    return float(result.stdout.strip())


def detect_tracks(ffmpeg: str, source: Path, total_duration: float) -> list[Track]:
    command = [
        ffmpeg,
        "-hide_banner",
        "-nostats",
        "-i",
        str(source),
        "-af",
        "silencedetect=noise=-32dB:d=1.2",
        "-f",
        "null",
        "NUL" if sys.platform == "win32" else "/dev/null",
    ]
    result = subprocess.run(
        command,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True,
    )

    starts = [float(value) for value in re.findall(r"silence_start:\s*([0-9.]+)", result.stderr)]
    ends = [float(value) for value in re.findall(r"silence_end:\s*([0-9.]+)", result.stderr)]
    boundaries: list[float] = [0.0]
    for silence_start, silence_end in zip(starts, ends):
        if silence_end - silence_start >= 1.2:
            boundary = (silence_start + silence_end) / 2
            if boundary - boundaries[-1] >= 30:
                boundaries.append(boundary)
    if total_duration - boundaries[-1] < 30 and len(boundaries) > 1:
        boundaries.pop()
    boundaries.append(total_duration)

    return [
        Track(number=index + 1, start=start, end=end)
        for index, (start, end) in enumerate(zip(boundaries, boundaries[1:]))
        if end - start >= 15
    ]


def analyse_energy(ffmpeg: str, source: Path, total_duration: float) -> list[float]:
    """Return one RMS dB value per second using low-rate mono PCM."""
    sample_rate = 2000
    command = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(source),
        "-vn",
        "-ac",
        "1",
        "-ar",
        str(sample_rate),
        "-f",
        "s16le",
        "-",
    ]
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if process.stdout is None:
        raise RuntimeError("ไม่สามารถอ่านข้อมูลเสียงจาก FFmpeg")

    values: list[float] = []
    bytes_per_second = sample_rate * 2
    while True:
        chunk = process.stdout.read(bytes_per_second)
        if not chunk:
            break
        samples = array.array("h")
        samples.frombytes(chunk[: len(chunk) - (len(chunk) % 2)])
        if sys.byteorder != "little":
            samples.byteswap()
        if not samples:
            values.append(-90.0)
            continue
        mean_square = sum(sample * sample for sample in samples) / len(samples)
        rms = math.sqrt(mean_square) / 32768.0
        values.append(20 * math.log10(max(rms, 1e-9)))

    stderr = process.stderr.read().decode("utf-8", errors="replace") if process.stderr else ""
    if process.wait() != 0:
        raise RuntimeError(f"FFmpeg วิเคราะห์เสียงไม่สำเร็จ: {stderr[-500:]}")
    expected = math.ceil(total_duration)
    if len(values) < min(10, expected):
        raise RuntimeError("ข้อมูลวิเคราะห์เสียงสั้นผิดปกติ")
    return values


def choose_length(track_duration: float) -> int:
    # Leave room around the chosen section so intros/outros are rarely selected.
    if track_duration >= 120:
        return 60
    if track_duration >= 80:
        return 45
    if track_duration >= 50:
        return 30
    return 15


def choose_clip(track: Track, energy: list[float]) -> tuple[float, int, float]:
    clip_length = choose_length(track.duration)
    margin_before = min(12, max(2, int(track.duration * 0.05)))
    margin_after = min(8, max(2, int(track.duration * 0.03)))
    first = max(math.ceil(track.start + margin_before), 0)
    last = min(math.floor(track.end - margin_after - clip_length), len(energy) - clip_length)
    if last < first:
        first = max(math.ceil(track.start), 0)
        last = min(math.floor(track.end - clip_length), len(energy) - clip_length)

    best_start = first
    best_score = -999.0
    step = 1 if clip_length <= 30 else 2
    for start in range(first, last + 1, step):
        window = energy[start : start + clip_length]
        if len(window) < clip_length:
            continue
        average = sum(window) / len(window)
        quiet_seconds = sum(1 for value in window if value < -35)
        consistency_penalty = max(window) - min(window)
        score = average - quiet_seconds * 0.7 - consistency_penalty * 0.03
        if score > best_score:
            best_score = score
            best_start = start

    # Move to a nearby local dip so the cut is less likely to begin mid-beat/phrase.
    search_from = max(first, best_start - 3)
    search_to = min(last, best_start + 2)
    if search_to >= search_from:
        snapped = min(range(search_from, search_to + 1), key=lambda pos: energy[pos])
        if energy[snapped] <= energy[best_start] - 1.0:
            best_start = snapped
    return float(best_start), clip_length, best_score


def format_time(seconds: float) -> str:
    whole = int(round(seconds))
    hours, remainder = divmod(whole, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def export_clip(
    ffmpeg: str,
    source: Path,
    destination: Path,
    start: float,
    length: int,
) -> None:
    fade_out = max(0, length - 0.35)
    audio_filter = (
        f"afade=t=in:st=0:d=0.15,"
        f"afade=t=out:st={fade_out}:d=0.35,"
        "loudnorm=I=-14:TP=-1.5:LRA=11"
    )
    run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-n",
            "-ss",
            f"{start:.3f}",
            "-t",
            str(length),
            "-i",
            str(source),
            "-af",
            audio_filter,
            "-c:a",
            "libmp3lame",
            "-b:a",
            "192k",
            str(destination),
        ]
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="ตัดเพลงรวมเป็นคลิป MP3 สำหรับ Reels อัตโนมัติ")
    parser.add_argument("input", nargs="?", help="ไฟล์ต้นฉบับ (ถ้าไม่ระบุจะเลือกไฟล์เสียงที่ใหญ่ที่สุด)")
    parser.add_argument("--max-songs", type=int, default=0, help="จำนวนเพลงสูงสุด; 0 = ทั้งหมด")
    parser.add_argument("--output", default="Reels_Cuts", help="ชื่อโฟลเดอร์ผลลัพธ์")
    parser.add_argument("--prefix", default="", help="คำนำหน้าชื่อคลิปและรายงาน ป้องกันชื่อชนเมื่อตัดหลายไฟล์")
    args = parser.parse_args()

    folder = Path.cwd()
    ffmpeg, ffprobe = locate_tools()
    source = choose_input(folder, args.input)
    output_folder = folder / args.output
    output_folder.mkdir(parents=True, exist_ok=True)
    prefix = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "-", args.prefix).strip(" .-")[:80]
    prefix = f"{prefix}_" if prefix else ""

    print(f"ไฟล์ต้นฉบับ: {source.name}")
    total_duration = probe_duration(ffprobe, source)
    print("กำลังหารอยแบ่งเพลง...")
    tracks = detect_tracks(ffmpeg, source, total_duration)
    if args.max_songs > 0:
        tracks = tracks[: args.max_songs]
    print(f"พบ {len(tracks)} ช่วงเพลง")

    print("กำลังวิเคราะห์หาท่อนที่เหมาะกับ Reels...")
    energy = analyse_energy(ffmpeg, source, total_duration)
    report_rows: list[dict[str, str | int]] = []

    for track in tracks:
        clip_start, clip_length, _score = choose_clip(track, energy)
        clip_end = clip_start + clip_length
        filename = f"{prefix}reels-{track.number:03d}-{clip_length}s.mp3"
        destination = output_folder / filename
        print(
            f"[{track.number:03d}/{len(tracks):03d}] "
            f"{format_time(clip_start)}–{format_time(clip_end)} -> {filename}"
        )
        if destination.exists():
            print(f"ข้ามไฟล์ที่มีแล้ว: {filename}")
        else:
            export_clip(ffmpeg, source, destination, clip_start, clip_length)
        report_rows.append(
            {
                "ลำดับ": track.number,
                "ไฟล์": filename,
                "ความยาว_วินาที": clip_length,
                "เริ่มในไฟล์ต้นฉบับ": format_time(clip_start),
                "จบในไฟล์ต้นฉบับ": format_time(clip_end),
                "ช่วงเพลงเริ่ม": format_time(track.start),
                "ช่วงเพลงจบ": format_time(track.end),
            }
        )

    report_path = output_folder / f"{prefix}รายการไฟล์.csv"
    with report_path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=["ลำดับ", "ไฟล์", "ความยาว_วินาที", "เริ่มในไฟล์ต้นฉบับ", "จบในไฟล์ต้นฉบับ", "ช่วงเพลงเริ่ม", "ช่วงเพลงจบ"])
        writer.writeheader()
        writer.writerows(report_rows)

    print(f"เสร็จแล้ว: {output_folder}")
    print(f"รายงาน: {report_path.name}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nยกเลิกโดยผู้ใช้", file=sys.stderr)
        raise SystemExit(130)
    except Exception as error:
        print(f"เกิดข้อผิดพลาด: {error}", file=sys.stderr)
        raise SystemExit(1)
