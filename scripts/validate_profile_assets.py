#!/usr/bin/env python3
"""Validate and preview the animated assets used by the public profile README.

The validator is intentionally deterministic and dependency-light: Pillow is
the only non-standard-library dependency.  It validates GitHub-facing image
markup and animation budgets, measures frame-to-frame motion, verifies that a
single stable palette is used, and writes local-only QA previews under tmp/.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import math
import re
import struct
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Sequence
from urllib.parse import unquote, urlsplit

from PIL import Image, ImageChops, ImageDraw, ImageFont, ImageStat


PROJECT_SLUGS = ("agent-sandbox", "mira", "automata", "spider-sense")
PRINCIPLE_SLUGS = ("authority", "evidence", "agency", "emergence", "boundaries")

PROJECT_MIN_SIZE = (900, 320)
PROJECT_MAX_SIZE = (960, 400)
PROJECT_MIN_FRAMES = 24
PROJECT_MAX_FRAMES = 180
PROJECT_MIN_DURATION_MS = 6_000
PROJECT_MAX_DURATION_MS = 18_000
PROJECT_PRACTICAL_BYTES = 2_500_000
PROJECT_HARD_BYTES = 3_500_000

PRINCIPLE_MIN_SIZE = (80, 80)
PRINCIPLE_MAX_SIZE = (112, 112)
PRINCIPLE_MIN_FRAMES = 8
PRINCIPLE_MAX_FRAMES = 30
PRINCIPLE_MIN_DURATION_MS = 3_000
PRINCIPLE_MAX_DURATION_MS = 8_000
PRINCIPLE_HARD_BYTES = 200_000

TOTAL_PRACTICAL_BYTES = 12_000_000
TOTAL_HARD_BYTES = 14_000_000
CHANGED_PIXEL_THRESHOLD = 6
CONTACT_SHEET_SAMPLES = 16


@dataclass
class Report:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def error(self, message: str) -> None:
        self.errors.append(message)
        print(f"ERROR: {message}")

    def warn(self, message: str) -> None:
        self.warnings.append(message)
        print(f"WARN:  {message}")

    def ok(self, message: str) -> None:
        print(f"OK:    {message}")


@dataclass(frozen=True)
class PaletteInfo:
    global_table_colors: int
    local_table_count: int
    distinct_table_hashes: int
    stable: bool


@dataclass
class GifMetrics:
    slug: str
    path: Path
    kind: str
    width: int
    height: int
    frames: int
    duration_ms: int
    loop: int | None
    file_size: int
    frame_durations: list[int]
    changed_percentages: list[float]
    luminance_deltas: list[float]
    duplicate_pairs: list[tuple[int, int]]
    loop_changed_percentage: float
    loop_luminance_delta: float
    actual_color_count: int
    palette: PaletteInfo
    decoded_frames: list[Image.Image]

    @property
    def max_changed_percentage(self) -> float:
        return max(self.changed_percentages, default=0.0)

    @property
    def max_changed_boundary(self) -> int:
        if not self.changed_percentages:
            return 0
        return self.changed_percentages.index(self.max_changed_percentage) + 1

    @property
    def max_luminance_delta(self) -> float:
        return max(self.luminance_deltas, default=0.0)


@dataclass(frozen=True)
class ReadmeImage:
    source: str
    alt: str | None
    location: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="Profile repository root (defaults to the parent of scripts/).",
    )
    parser.add_argument(
        "--preview-dir",
        type=Path,
        default=None,
        help="QA output directory (defaults to tmp/profile-animation-preview).",
    )
    parser.add_argument(
        "--no-preview",
        action="store_true",
        help="Run validation without writing contact sheets or the HTML QA page.",
    )
    return parser.parse_args()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def human_bytes(value: int) -> str:
    if value < 1024:
        return f"{value} B"
    if value < 1024 * 1024:
        return f"{value / 1024:.1f} KiB"
    return f"{value / 1024 / 1024:.2f} MiB"


def strip_markdown_destination(value: str) -> str:
    value = value.strip()
    if value.startswith("<") and value.endswith(">"):
        value = value[1:-1]
    # Markdown image titles follow the URL after whitespace. Local asset paths
    # in this repository do not contain unescaped spaces.
    return value.split(maxsplit=1)[0].strip()


def extract_readme_images(readme: str) -> list[ReadmeImage]:
    images: list[ReadmeImage] = []
    markdown_pattern = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")
    for match in markdown_pattern.finditer(readme):
        images.append(
            ReadmeImage(
                source=strip_markdown_destination(match.group(2)),
                alt=match.group(1).strip(),
                location=f"Markdown image at character {match.start()}",
            )
        )

    for match in re.finditer(r"<img\b[^>]*>", readme, flags=re.IGNORECASE | re.DOTALL):
        tag = match.group(0)
        source_match = re.search(r"\bsrc\s*=\s*([\"'])(.*?)\1", tag, flags=re.IGNORECASE | re.DOTALL)
        alt_match = re.search(r"\balt\s*=\s*([\"'])(.*?)\1", tag, flags=re.IGNORECASE | re.DOTALL)
        if source_match:
            images.append(
                ReadmeImage(
                    source=source_match.group(2).strip(),
                    alt=alt_match.group(2).strip() if alt_match else None,
                    location=f"HTML img at character {match.start()}",
                )
            )

    # A picture source has no alt of its own; its sibling img carries the
    # accessible description. We still validate each srcset path.
    for match in re.finditer(r"<source\b[^>]*>", readme, flags=re.IGNORECASE | re.DOTALL):
        tag = match.group(0)
        source_match = re.search(r"\bsrcset\s*=\s*([\"'])(.*?)\1", tag, flags=re.IGNORECASE | re.DOTALL)
        if source_match:
            for candidate in source_match.group(2).split(","):
                source = candidate.strip().split(maxsplit=1)[0]
                if source:
                    images.append(
                        ReadmeImage(
                            source=source,
                            alt=None,
                            location=f"HTML source at character {match.start()}",
                        )
                    )
    return images


def is_remote(value: str) -> bool:
    parsed = urlsplit(value)
    return parsed.scheme.lower() in {"http", "https"} or value.startswith("//")


def local_asset_path(repo_root: Path, source: str) -> Path | None:
    if is_remote(source) or source.startswith(("data:", "#")):
        return None
    parsed = urlsplit(source)
    # Normalize URL separators without assuming the host platform; Path.parts
    # below then resolves the repository-relative components safely.
    decoded = unquote(parsed.path).replace("\\", "/")
    while decoded.startswith("./"):
        decoded = decoded[2:]
    if not decoded:
        return None
    return repo_root.joinpath(*Path(decoded).parts)


def alt_is_meaningful(value: str | None) -> bool:
    if value is None:
        return False
    normalized = re.sub(r"\s+", " ", value).strip()
    if len(normalized) < 12:
        return False
    return normalized.casefold() not in {
        "image",
        "animation",
        "animated image",
        "profile image",
        "banner image",
        "project image",
    }


def validate_readme(repo_root: Path, report: Report) -> list[ReadmeImage]:
    readme_path = repo_root / "README.md"
    if not readme_path.is_file():
        report.error("README.md is missing")
        return []
    readme = readme_path.read_text(encoding="utf-8")
    images = extract_readme_images(readme)
    if not images:
        report.error("README.md contains no images")
        return []

    remote_images = [image for image in images if is_remote(image.source)]
    for image in remote_images:
        report.error(f"remote/tracking-capable README image is not allowed: {image.source}")
    for image in images:
        if image.source.startswith("data:"):
            report.error(f"embedded data image is not allowed: {image.location}")
            continue
        path = local_asset_path(repo_root, image.source)
        if path is not None and not path.is_file():
            report.error(f"README image path does not exist: {image.source}")
        if image.location.startswith(("Markdown image", "HTML img")) and not alt_is_meaningful(image.alt):
            report.error(f"README image lacks meaningful alt text: {image.source}")

    lowered = readme.casefold()
    for forbidden in ("<script", "<iframe", "visitor-badge", "hits.seeyoufarm", "komarev.com/ghpvc"):
        if forbidden in lowered:
            report.error(f"README contains a tracking or executable pattern: {forbidden}")

    report.ok(f"README references {len(images)} local image candidates with no remote image URLs" if not remote_images else f"README image scan completed ({len(images)} candidates)")
    return images


def parse_gif_palette_tables(path: Path) -> PaletteInfo:
    """Parse GIF color-table declarations without decoding LZW image data."""
    data = path.read_bytes()
    if len(data) < 13 or data[:6] not in (b"GIF87a", b"GIF89a"):
        return PaletteInfo(0, 0, 0, False)
    packed = data[10]
    global_colors = 2 ** ((packed & 0x07) + 1) if packed & 0x80 else 0
    position = 13
    table_hashes: list[str] = []
    if global_colors:
        size = global_colors * 3
        if position + size > len(data):
            return PaletteInfo(global_colors, 0, 0, False)
        table_hashes.append(sha256_bytes(data[position : position + size]))
        position += size

    local_count = 0
    try:
        while position < len(data):
            marker = data[position]
            if marker == 0x3B:  # trailer
                break
            if marker == 0x21:  # extension + data sub-blocks
                position += 2
                while True:
                    block_size = data[position]
                    position += 1
                    if block_size == 0:
                        break
                    position += block_size
                continue
            if marker != 0x2C:  # image descriptor
                raise ValueError(f"unexpected GIF marker 0x{marker:02x}")
            if position + 10 > len(data):
                raise ValueError("truncated image descriptor")
            image_packed = data[position + 9]
            position += 10
            if image_packed & 0x80:
                local_colors = 2 ** ((image_packed & 0x07) + 1)
                size = local_colors * 3
                table_hashes.append(sha256_bytes(data[position : position + size]))
                position += size
                local_count += 1
            position += 1  # LZW minimum code size
            while True:
                block_size = data[position]
                position += 1
                if block_size == 0:
                    break
                position += block_size
    except (IndexError, ValueError):
        return PaletteInfo(global_colors, local_count, len(set(table_hashes)), False)

    distinct = len(set(table_hashes))
    return PaletteInfo(
        global_table_colors=global_colors,
        local_table_count=local_count,
        distinct_table_hashes=distinct,
        stable=bool(global_colors) and distinct == 1,
    )


def changed_percentage(first: Image.Image, second: Image.Image) -> float:
    difference = ImageChops.difference(first, second)
    red, green, blue = difference.split()
    maximum_channel_delta = ImageChops.lighter(ImageChops.lighter(red, green), blue)
    thresholded = maximum_channel_delta.point(
        lambda value: 255 if value >= CHANGED_PIXEL_THRESHOLD else 0
    )
    histogram = thresholded.histogram()
    changed = sum(histogram[1:])
    return changed * 100.0 / (first.width * first.height)


def mean_luminance(image: Image.Image) -> float:
    return float(ImageStat.Stat(image.convert("L")).mean[0])


def inspect_gif(path: Path, slug: str, kind: str) -> GifMetrics:
    palette = parse_gif_palette_tables(path)
    decoded: list[Image.Image] = []
    durations: list[int] = []
    colors: set[tuple[int, int, int]] = set()
    with Image.open(path) as image:
        width, height = image.size
        frames = int(getattr(image, "n_frames", 1))
        loop = image.info.get("loop")
        default_duration = int(image.info.get("duration", 0) or 0)
        for index in range(frames):
            image.seek(index)
            duration = int(image.info.get("duration", default_duration) or 0)
            durations.append(duration)
            frame = image.convert("RGB").copy()
            decoded.append(frame)
            frame_colors = frame.getcolors(maxcolors=1_000_000)
            if frame_colors is not None:
                colors.update(color for _, color in frame_colors)

    changed = [changed_percentage(first, second) for first, second in zip(decoded, decoded[1:])]
    luminances = [mean_luminance(frame) for frame in decoded]
    luminance_deltas = [abs(first - second) * 100.0 / 255.0 for first, second in zip(luminances, luminances[1:])]
    duplicates = [(index, index + 1) for index, value in enumerate(changed) if value <= 0.001]
    loop_changed = changed_percentage(decoded[-1], decoded[0]) if len(decoded) > 1 else 0.0
    loop_luminance = abs(luminances[-1] - luminances[0]) * 100.0 / 255.0 if len(decoded) > 1 else 0.0
    return GifMetrics(
        slug=slug,
        path=path,
        kind=kind,
        width=width,
        height=height,
        frames=frames,
        duration_ms=sum(durations),
        loop=int(loop) if loop is not None else None,
        file_size=path.stat().st_size,
        frame_durations=durations,
        changed_percentages=changed,
        luminance_deltas=luminance_deltas,
        duplicate_pairs=duplicates,
        loop_changed_percentage=loop_changed,
        loop_luminance_delta=loop_luminance,
        actual_color_count=len(colors),
        palette=palette,
        decoded_frames=decoded,
    )


def validate_gif(metrics: GifMetrics, poster_path: Path, report: Report) -> None:
    label = metrics.slug
    if metrics.frames <= 1:
        report.error(f"{label}: GIF is not animated")
    if metrics.loop != 0:
        report.error(f"{label}: GIF must loop infinitely (loop=0, found {metrics.loop!r})")
    if any(duration <= 0 for duration in metrics.frame_durations):
        bad = [index for index, value in enumerate(metrics.frame_durations) if value <= 0]
        report.error(f"{label}: zero/invalid frame durations at {bad}")

    if metrics.kind == "project":
        if not (
            PROJECT_MIN_SIZE[0] <= metrics.width <= PROJECT_MAX_SIZE[0]
            and PROJECT_MIN_SIZE[1] <= metrics.height <= PROJECT_MAX_SIZE[1]
        ):
            report.error(
                f"{label}: {metrics.width}x{metrics.height} is outside project target "
                f"{PROJECT_MIN_SIZE[0]}-{PROJECT_MAX_SIZE[0]} x {PROJECT_MIN_SIZE[1]}-{PROJECT_MAX_SIZE[1]}"
            )
        if not PROJECT_MIN_FRAMES <= metrics.frames <= PROJECT_MAX_FRAMES:
            report.error(f"{label}: {metrics.frames} frames is outside {PROJECT_MIN_FRAMES}-{PROJECT_MAX_FRAMES}")
        if not PROJECT_MIN_DURATION_MS <= metrics.duration_ms <= PROJECT_MAX_DURATION_MS:
            report.error(f"{label}: {metrics.duration_ms} ms is outside {PROJECT_MIN_DURATION_MS}-{PROJECT_MAX_DURATION_MS} ms")
        if metrics.file_size > PROJECT_HARD_BYTES:
            report.error(f"{label}: {human_bytes(metrics.file_size)} exceeds the 3.5 MB hard ceiling")
        elif metrics.file_size > PROJECT_PRACTICAL_BYTES:
            report.warn(f"{label}: {human_bytes(metrics.file_size)} exceeds the practical 2.5 MB target")
    else:
        if not (
            PRINCIPLE_MIN_SIZE[0] <= metrics.width <= PRINCIPLE_MAX_SIZE[0]
            and PRINCIPLE_MIN_SIZE[1] <= metrics.height <= PRINCIPLE_MAX_SIZE[1]
        ):
            report.error(f"{label}: {metrics.width}x{metrics.height} is outside principle target 80-112 px square")
        if not PRINCIPLE_MIN_FRAMES <= metrics.frames <= PRINCIPLE_MAX_FRAMES:
            report.error(f"{label}: {metrics.frames} frames is outside {PRINCIPLE_MIN_FRAMES}-{PRINCIPLE_MAX_FRAMES}")
        if not PRINCIPLE_MIN_DURATION_MS <= metrics.duration_ms <= PRINCIPLE_MAX_DURATION_MS:
            report.error(f"{label}: {metrics.duration_ms} ms is outside {PRINCIPLE_MIN_DURATION_MS}-{PRINCIPLE_MAX_DURATION_MS} ms")
        if metrics.file_size > PRINCIPLE_HARD_BYTES:
            report.error(f"{label}: {human_bytes(metrics.file_size)} exceeds the 200 KB principle budget")

    if not poster_path.is_file():
        report.error(f"{label}: static poster is missing: {poster_path.relative_to(poster_path.parents[2])}")
    else:
        with Image.open(poster_path) as poster:
            if poster.size != (metrics.width, metrics.height):
                report.error(f"{label}: poster size {poster.size} does not match GIF {(metrics.width, metrics.height)}")

    if not metrics.palette.stable:
        report.error(
            f"{label}: palette is not globally stable "
            f"({metrics.palette.local_table_count} local tables, "
            f"{metrics.palette.distinct_table_hashes} distinct palette tables)"
        )

    if metrics.duplicate_pairs:
        preview = ", ".join(f"{a}->{b}" for a, b in metrics.duplicate_pairs[:8])
        report.warn(f"{label}: duplicate adjacent transition frames detected ({preview})")
    if metrics.max_changed_percentage > 70.0:
        report.warn(
            f"{label}: inspect motion outlier at frame {metrics.max_changed_boundary}; "
            f"{metrics.max_changed_percentage:.2f}% of pixels changed"
        )
    if metrics.max_luminance_delta > 10.0:
        report.warn(f"{label}: maximum adjacent luminance jump is {metrics.max_luminance_delta:.2f} percentage points")
    if metrics.loop_changed_percentage > 40.0:
        report.warn(f"{label}: loop seam changes {metrics.loop_changed_percentage:.2f}% of pixels; inspect the reset")
    if metrics.loop_luminance_delta > 10.0:
        report.warn(f"{label}: loop seam luminance jump is {metrics.loop_luminance_delta:.2f} percentage points")
    abrupt_after_holds = [
        index
        for index, (duration, changed) in enumerate(
            zip(metrics.frame_durations[:-1], metrics.changed_percentages)
        )
        if duration >= 300 and changed > 20.0
    ]
    if abrupt_after_holds:
        report.warn(
            f"{label}: substantial changes follow long-held frames at boundaries "
            + ", ".join(f"{index}->{index + 1}" for index in abrupt_after_holds[:8])
        )


def expected_asset_paths(repo_root: Path) -> Iterable[tuple[str, str, Path, Path]]:
    animation_dir = repo_root / "assets" / "animations"
    for slug in PROJECT_SLUGS:
        yield slug, "project", animation_dir / f"{slug}.gif", animation_dir / f"{slug}-poster.png"
    for slug in PRINCIPLE_SLUGS:
        yield slug, "principle", animation_dir / "principles" / f"{slug}.gif", animation_dir / "principles" / f"{slug}-poster.png"


def validate_manifest(repo_root: Path, metrics_by_slug: dict[str, GifMetrics], report: Report) -> None:
    path = repo_root / "assets" / "animations" / "manifest.json"
    if not path.is_file():
        report.error("assets/animations/manifest.json is missing")
        return
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        report.error(f"animation manifest is invalid: {exc}")
        return
    entries = {entry.get("slug"): entry for entry in manifest.get("assets", []) if isinstance(entry, dict)}
    for slug, metrics in metrics_by_slug.items():
        entry = entries.get(slug)
        if entry is None:
            report.error(f"{slug}: missing from animation manifest")
            continue
        expected = {
            "width": metrics.width,
            "height": metrics.height,
            "frames": metrics.frames,
            "duration_ms": metrics.duration_ms,
            "file_size": metrics.file_size,
            "sha256": sha256_file(metrics.path),
        }
        for key, value in expected.items():
            if entry.get(key) != value:
                report.error(f"{slug}: manifest {key}={entry.get(key)!r}, actual={value!r}")
        if not alt_is_meaningful(str(entry.get("alt", ""))):
            report.error(f"{slug}: manifest alt text is missing or not meaningful")
    extra = sorted(set(entries) - set(metrics_by_slug))
    if extra:
        report.warn(f"manifest has unexpected animation entries: {', '.join(extra)}")


def validate_readme_asset_coverage(images: Sequence[ReadmeImage], repo_root: Path, report: Report) -> None:
    local_sources: set[str] = set()
    for image in images:
        path = local_asset_path(repo_root, image.source)
        if path is not None:
            try:
                local_sources.add(path.resolve().relative_to(repo_root.resolve()).as_posix())
            except ValueError:
                report.error(f"README image escapes repository root: {image.source}")
    for slug, kind, gif, poster in expected_asset_paths(repo_root):
        gif_relative = gif.relative_to(repo_root).as_posix()
        poster_relative = poster.relative_to(repo_root).as_posix()
        if gif_relative not in local_sources:
            report.error(f"{slug}: GIF is not referenced by README.md")
        if poster_relative not in local_sources:
            report.error(f"{slug}: reduced-motion poster is not referenced by README.md")


def sample_indices(metrics: GifMetrics, count: int = CONTACT_SHEET_SAMPLES) -> list[int]:
    frame_count = metrics.frames
    if frame_count <= count:
        return list(range(frame_count))
    # Ten timeline samples preserve the whole story. The six remaining slots
    # prioritize both sides of the three largest transition boundaries.
    evenly = {
        round(index * (frame_count - 1) / 9)
        for index in range(10)
    }
    boundaries = sorted(
        range(1, frame_count),
        key=lambda index: metrics.changed_percentages[index - 1],
        reverse=True,
    )
    selected = set(evenly)
    for boundary in boundaries:
        for index in (boundary - 1, boundary):
            if len(selected) >= count:
                break
            selected.add(index)
        if len(selected) >= count:
            break
    if len(selected) < 12:
        for index in range(frame_count):
            selected.add(index)
            if len(selected) >= min(count, frame_count):
                break
    return sorted(selected)[:count]


def cumulative_times(durations: Sequence[int]) -> list[int]:
    result: list[int] = []
    elapsed = 0
    for duration in durations:
        result.append(elapsed)
        elapsed += duration
    return result


def fit_thumbnail(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    max_width, max_height = size
    scale = min(max_width / image.width, max_height / image.height)
    result = image.resize(
        (max(1, round(image.width * scale)), max(1, round(image.height * scale))),
        Image.Resampling.NEAREST,
    )
    return result


def create_contact_sheet(metrics: GifMetrics, output: Path) -> None:
    indices = sample_indices(metrics)
    columns = 4
    rows = math.ceil(len(indices) / columns)
    cell_width = 252
    image_height = 95
    label_height = 24
    header_height = 48
    cell_height = image_height + label_height + 12
    sheet = Image.new("RGB", (columns * cell_width, header_height + rows * cell_height), (7, 17, 31))
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default()
    draw.text((12, 8), f"{metrics.slug} - deterministic transition QA", fill=(247, 243, 232), font=font)
    draw.text(
        (12, 26),
        f"{metrics.frames} frames · {metrics.duration_ms / 1000:.2f}s · peak change {metrics.max_changed_percentage:.2f}% · seam {metrics.loop_changed_percentage:.2f}%",
        fill=(174, 189, 202),
        font=font,
    )
    times = cumulative_times(metrics.frame_durations)
    top_boundaries = set(
        sorted(
            range(1, metrics.frames),
            key=lambda index: metrics.changed_percentages[index - 1],
            reverse=True,
        )[:3]
    )
    for slot, frame_index in enumerate(indices):
        column = slot % columns
        row = slot // columns
        left = column * cell_width + 6
        top = header_height + row * cell_height
        thumb = fit_thumbnail(metrics.decoded_frames[frame_index], (240, image_height))
        x = left + (240 - thumb.width) // 2
        y = top + (image_height - thumb.height) // 2
        sheet.paste(thumb, (x, y))
        boundary = frame_index in top_boundaries
        outline = (215, 138, 75) if boundary else (42, 64, 86)
        draw.rectangle((left - 1, top - 1, left + 241, top + image_height), outline=outline, width=2 if boundary else 1)
        delta = metrics.changed_percentages[frame_index - 1] if frame_index > 0 else metrics.loop_changed_percentage
        marker = " transition" if boundary else ""
        draw.text(
            (left, top + image_height + 4),
            f"f{frame_index:03d}  t={times[frame_index] / 1000:05.2f}s  dPx={delta:05.1f}%{marker}",
            fill=(69, 203, 209) if boundary else (174, 189, 202),
            font=font,
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output, format="PNG", optimize=True)


def relative_href(from_dir: Path, target: Path) -> str:
    import os

    return Path(os.path.relpath(target, from_dir)).as_posix()


def create_preview_html(projects: Sequence[GifMetrics], preview_dir: Path) -> None:
    cards: list[str] = []
    contact_cards: list[str] = []
    for metrics in projects:
        gif_href = html.escape(relative_href(preview_dir, metrics.path), quote=True)
        poster = metrics.path.with_name(f"{metrics.slug}-poster.png")
        poster_href = html.escape(relative_href(preview_dir, poster), quote=True)
        contact = preview_dir / f"{metrics.slug}-contact-sheet.png"
        contact_href = html.escape(relative_href(preview_dir, contact), quote=True)
        cards.append(
            f"""
            <article class="project-card">
              <h2>{html.escape(metrics.slug.replace('-', ' ').title())}</h2>
              <picture>
                <source media="(prefers-reduced-motion: reduce)" srcset="{poster_href}">
                <img src="{gif_href}" alt="Local animation QA for {html.escape(metrics.slug)}">
              </picture>
              <dl>
                <div><dt>Frames</dt><dd>{metrics.frames}</dd></div>
                <div><dt>Duration</dt><dd>{metrics.duration_ms / 1000:.2f}s</dd></div>
                <div><dt>Peak change</dt><dd>{metrics.max_changed_percentage:.2f}%</dd></div>
                <div><dt>Peak luminance Δ</dt><dd>{metrics.max_luminance_delta:.2f}pp</dd></div>
                <div><dt>Loop seam</dt><dd>{metrics.loop_changed_percentage:.2f}%</dd></div>
                <div><dt>Colors</dt><dd>{metrics.actual_color_count}</dd></div>
              </dl>
            </article>"""
        )
        contact_cards.append(
            f'<figure><img src="{contact_href}" alt="{html.escape(metrics.slug)} sampled transition contact sheet"><figcaption>{html.escape(metrics.slug)}</figcaption></figure>'
        )

    html_text = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Profile animation QA</title>
  <style>
    :root {{ color-scheme: dark; --navy:#07111f; --surface:#101b2b; --steel:#2a4056; --cyan:#45cbd1; --copper:#d78a4b; --cream:#f7f3e8; --muted:#aebdca; }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; padding:24px; background:var(--navy); color:var(--cream); font:15px/1.5 system-ui,sans-serif; }}
    header, main {{ width:min(100%, 1200px); margin:auto; }}
    h1 {{ margin:.1em 0; }} p {{ color:var(--muted); }}
    .controls {{ position:sticky; top:0; z-index:2; padding:10px; background:rgba(7,17,31,.94); border:1px solid var(--steel); }}
    input {{ position:absolute; opacity:0; }} label {{ display:inline-block; padding:5px 10px; color:var(--cyan); cursor:pointer; }}
    #native:checked ~ main .stage {{ width:960px; }} #github:checked ~ main .stage {{ width:720px; }} #mobile:checked ~ main .stage {{ width:390px; }}
    .stage {{ max-width:100%; margin:24px auto; transition:width .2s ease; }}
    .project-card {{ margin:22px 0 36px; padding:16px; border:1px solid var(--steel); border-radius:12px; background:var(--surface); }}
    .project-card img {{ display:block; width:100%; height:auto; image-rendering:pixelated; border-radius:6px; }}
    dl {{ display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:8px; }} dl div {{ border-left:2px solid var(--copper); padding-left:8px; }} dt {{ color:var(--muted); }} dd {{ margin:0; color:var(--cyan); }}
    .contact-grid {{ display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:16px; }} figure {{ margin:0; }} figure img {{ width:100%; height:auto; }} figcaption {{ color:var(--muted); }}
    @media (max-width:600px) {{ body {{ padding:10px; }} dl,.contact-grid {{ grid-template-columns:1fr; }} }}
    @media (prefers-reduced-motion:reduce) {{ * {{ animation:none!important; transition:none!important; }} }}
  </style>
</head>
<body>
  <input id="native" name="width" type="radio"><input id="github" name="width" type="radio" checked><input id="mobile" name="width" type="radio">
  <header>
    <h1>Profile animation QA</h1>
    <p>All four loops run together in README order. Use the width controls to inspect native, typical GitHub, and mobile rendering. System reduced-motion preference swaps GIFs for posters.</p>
    <div class="controls"><strong>Preview width:</strong> <label for="native">960 px</label><label for="github">720 px</label><label for="mobile">390 px</label></div>
  </header>
  <main>
    <section class="stage">{''.join(cards)}</section>
    <h2>Sampled frames and transition boundaries</h2>
    <section class="contact-grid">{''.join(contact_cards)}</section>
  </main>
</body>
</html>
"""
    preview_dir.mkdir(parents=True, exist_ok=True)
    (preview_dir / "all-projects-preview.html").write_text(html_text, encoding="utf-8")


def print_metrics_table(metrics: Sequence[GifMetrics]) -> None:
    print("\nAnimation motion report")
    print(
        f"{'asset':<16} {'size':>9} {'frames':>6} {'time':>7} {'bytes':>10} "
        f"{'max dPx':>9} {'max dY':>8} {'seam':>8} {'used':>5} {'GCT':>5} {'LCT':>5}"
    )
    print("-" * 104)
    for item in metrics:
        print(
            f"{item.slug:<16} {item.width:>4}x{item.height:<4} {item.frames:>6} "
            f"{item.duration_ms / 1000:>6.2f}s {human_bytes(item.file_size):>10} "
            f"{item.max_changed_percentage:>8.2f}% {item.max_luminance_delta:>7.2f} "
            f"{item.loop_changed_percentage:>7.2f}% {item.actual_color_count:>5} "
            f"{item.palette.global_table_colors:>5} {item.palette.local_table_count:>5}"
        )


def validate_repository_identity(repo_root: Path, report: Report) -> None:
    git_config = repo_root / ".git" / "config"
    if not git_config.is_file():
        report.error(f"repository root is not a Git working tree: {repo_root}")
        return
    config = git_config.read_text(encoding="utf-8", errors="replace").casefold()
    if "konfusi0n/konfusi0n" not in config:
        report.warn("Git origin does not visibly identify Konfusi0n/Konfusi0n; verify public-profile scope manually")
    else:
        report.ok("repository identity is scoped to Konfusi0n/Konfusi0n")


def main() -> int:
    args = parse_args()
    repo_root = args.repo_root.resolve()
    preview_dir = (args.preview_dir or repo_root / "tmp" / "profile-animation-preview").resolve()
    report = Report()
    validate_repository_identity(repo_root, report)
    readme_images = validate_readme(repo_root, report)

    all_metrics: list[GifMetrics] = []
    metrics_by_slug: dict[str, GifMetrics] = {}
    for slug, kind, gif_path, poster_path in expected_asset_paths(repo_root):
        if not gif_path.is_file():
            report.error(f"{slug}: expected GIF is missing: {gif_path.relative_to(repo_root)}")
            continue
        try:
            metrics = inspect_gif(gif_path, slug, kind)
        except (OSError, ValueError, EOFError, struct.error) as exc:
            report.error(f"{slug}: could not inspect GIF: {exc}")
            continue
        validate_gif(metrics, poster_path, report)
        all_metrics.append(metrics)
        metrics_by_slug[slug] = metrics

    validate_readme_asset_coverage(readme_images, repo_root, report)
    validate_manifest(repo_root, metrics_by_slug, report)

    total_bytes = sum(item.file_size for item in all_metrics)
    if total_bytes > TOTAL_HARD_BYTES:
        report.error(f"total GIF weight {human_bytes(total_bytes)} exceeds the 14 MB hard ceiling")
    elif total_bytes > TOTAL_PRACTICAL_BYTES:
        report.warn(f"total GIF weight {human_bytes(total_bytes)} exceeds the practical 12 MB target")
    else:
        report.ok(f"total GIF weight is {human_bytes(total_bytes)}")

    print_metrics_table(all_metrics)
    projects = [metrics_by_slug[slug] for slug in PROJECT_SLUGS if slug in metrics_by_slug]
    if not args.no_preview and projects:
        for metrics in projects:
            create_contact_sheet(metrics, preview_dir / f"{metrics.slug}-contact-sheet.png")
        create_preview_html(projects, preview_dir)
        report.ok(f"wrote deterministic QA previews to {preview_dir}")

    print(f"\nValidation summary: {len(report.errors)} error(s), {len(report.warnings)} warning(s)")
    return 1 if report.errors else 0


if __name__ == "__main__":
    sys.exit(main())
