#!/usr/bin/env python3
"""Build deterministic animated assets for the public profile README.

The project stories are assembled from four-panel user-supplied storyboard
sheets. Principle glyphs are procedural. The script uses only Pillow and the
Python standard library; it never reads private repositories or network data.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageStat


LOGICAL_SIZE = (480, 180)
OUTPUT_SIZE = (960, 360)
GLYPH_LOGICAL_SIZE = (48, 48)
GLYPH_OUTPUT_SIZE = (96, 96)
SEED_NAMESPACE = "konfusi0n-profile-animations-v1"

NAVY = (7, 17, 31)
NAVY_2 = (11, 23, 39)
SURFACE = (16, 27, 43)
STEEL = (42, 64, 86)
STEEL_LIGHT = (77, 109, 135)
MUTED = (174, 189, 202)
CYAN = (69, 203, 209)
CYAN_DIM = (37, 112, 124)
COPPER = (215, 138, 75)
COPPER_DIM = (128, 78, 49)
CREAM = (240, 207, 150)
CREAM_LIGHT = (247, 243, 232)


@dataclass(frozen=True)
class ProjectSpec:
    slug: str
    source_arg: str
    crop_y: tuple[float, float]
    focus_aspect: float
    offset_ms: int
    accent: tuple[int, int, int]
    secondary: tuple[int, int, int]
    alt: str


PROJECTS = (
    ProjectSpec(
        slug="agent-sandbox",
        source_arg="agent_sandbox",
        crop_y=(0.03, 0.97),
        focus_aspect=1.10,
        offset_ms=0,
        accent=COPPER,
        secondary=CYAN,
        alt=(
            "Pixel-art Agent Sandbox story: agents gather resources, test discoveries, "
            "build roads and workshops, and form a connected civilization around a luminous citadel."
        ),
    ),
    ProjectSpec(
        slug="mira",
        source_arg="mira",
        crop_y=(0.03, 0.97),
        focus_aspect=0.94,
        offset_ms=800,
        accent=CYAN,
        secondary=COPPER,
        alt=(
            "Pixel-art Mira story: a voice node branches to sources, returns evidence, "
            "assembles memory and creative tools, and resolves into an operator-controlled collaboration citadel."
        ),
    ),
    ProjectSpec(
        slug="automata",
        source_arg="automata",
        crop_y=(0.03, 0.97),
        focus_aspect=1.16,
        offset_ms=1600,
        accent=COPPER,
        secondary=CYAN,
        alt=(
            "Pixel-art Automata story: an orchestrator scopes work across bounded agents, "
            "routes evidence through validation gates, and records handoffs in architecture memory."
        ),
    ),
    ProjectSpec(
        slug="spider-sense",
        source_arg="spider_sense",
        crop_y=(0.04, 0.96),
        focus_aspect=1.08,
        offset_ms=2400,
        accent=CYAN,
        secondary=COPPER,
        alt=(
            "Pixel-art Spider Sense story: radar discovers sources, evidence flows through "
            "contradiction and freshness checks, and ranked claims resolve into a traceable synthesis."
        ),
    ),
)


GLYPH_ALTS = {
    "authority": "A proposal enters a gate; a validated-state pulse exits while rejected paths remain closed.",
    "evidence": "Three source nodes illuminate in sequence and retain visible paths to a central evidence ledger.",
    "agency": "An agent moves within a scope ring bounded by permission, cost, memory, and side-effect rails.",
    "emergence": "Simple connected nodes branch into interoperable structures that form a miniature neural citadel.",
    "boundaries": "Simulation, memory, inference, generation, and verification orbit as distinct but connected nodes.",
}

GLYPH_OFFSETS = {
    "authority": 100,
    "evidence": 1200,
    "agency": 2400,
    "emergence": 3600,
    "boundaries": 4800,
}

TRANSITION_MODES = {
    "agent-sandbox": ("bottom_up", "branch_growth", "branch_growth"),
    "mira": ("waveform", "path_out", "radial"),
    "automata": ("path_out", "path_out", "branch_growth"),
    "spider-sense": ("source_convergence", "path_out", "radial"),
}


def stable_seed(label: str) -> int:
    digest = hashlib.sha256(f"{SEED_NAMESPACE}:{label}".encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def smoothstep(value: float) -> float:
    value = clamp01(value)
    return value * value * (3.0 - 2.0 * value)


def smootherstep(value: float) -> float:
    value = clamp01(value)
    return value * value * value * (value * (value * 6.0 - 15.0) + 10.0)


def ease_in_out_cubic(value: float) -> float:
    value = clamp01(value)
    return 4.0 * value**3 if value < 0.5 else 1.0 - ((-2.0 * value + 2.0) ** 3) / 2.0


def ease_out_back(value: float) -> float:
    value = clamp01(value)
    overshoot = 1.70158
    return 1.0 + (overshoot + 1.0) * (value - 1.0) ** 3 + overshoot * (value - 1.0) ** 2


def lerp(start: float, end: float, progress: float) -> float:
    return start + (end - start) * clamp01(progress)


BAYER_8 = (
    (0, 48, 12, 60, 3, 51, 15, 63),
    (32, 16, 44, 28, 35, 19, 47, 31),
    (8, 56, 4, 52, 11, 59, 7, 55),
    (40, 24, 36, 20, 43, 27, 39, 23),
    (2, 50, 14, 62, 1, 49, 13, 61),
    (34, 18, 46, 30, 33, 17, 45, 29),
    (10, 58, 6, 54, 9, 57, 5, 53),
    (42, 26, 38, 22, 41, 25, 37, 21),
)


def reveal_threshold(mode: str, x: int, y: int, width: int, height: int) -> float:
    nx = x / max(1, width - 1)
    ny = y / max(1, height - 1)
    dx = nx - 0.5
    dy = ny - 0.5
    radial = min(1.0, math.sqrt(dx * dx + dy * dy) / 0.7072)

    if mode == "bottom_up":
        geometric = 1.0 - ny
    elif mode == "path_out":
        geometric = clamp01(nx * 0.72 + abs(ny - 0.56) * 0.56)
    elif mode == "branch_growth":
        trunk = abs(nx - 0.5) * 1.8 + (1.0 - ny) * 0.24
        left_branch = abs(ny - (1.12 * nx + 0.08)) * 1.7 + nx * 0.12
        right_branch = abs(ny - (-1.12 * nx + 1.20)) * 1.7 + (1.0 - nx) * 0.12
        geometric = clamp01(min(trunk, left_branch, right_branch))
    elif mode == "source_convergence":
        sources = ((0.06, 0.18), (0.94, 0.18), (0.06, 0.82), (0.94, 0.82), (0.5, 0.04))
        geometric = clamp01(min(math.dist((nx, ny), source) for source in sources) / 0.70)
    elif mode == "waveform":
        wave_y = 0.5 + math.sin(nx * math.tau * 2.0) * 0.10
        geometric = clamp01(nx * 0.48 + abs(ny - wave_y) * 0.90)
    elif mode == "edge_in":
        geometric = 1.0 - radial
    else:  # center_out and radial
        geometric = radial

    ordered = (BAYER_8[y % 8][x % 8] + 0.5) / 64.0
    return clamp01(geometric * 0.82 + ordered * 0.18)


def ordered_reveal(old: Image.Image, new: Image.Image, progress: float, mode: str) -> Image.Image:
    if old.size != new.size:
        raise ValueError("ordered reveal frames must share dimensions")
    if progress <= 0.0:
        return old.copy()
    if progress >= 1.0:
        return new.copy()
    mask = Image.new("L", old.size, 0)
    pixels = mask.load()
    for y in range(mask.height):
        for x in range(mask.width):
            if progress >= reveal_threshold(mode, x, y, mask.width, mask.height):
                pixels[x, y] = 255
    return Image.composite(new, old, mask)


def draw_partial_path(
    draw: ImageDraw.ImageDraw,
    points: Sequence[tuple[int, int]],
    progress: float,
    color: tuple[int, int, int],
    width: int = 1,
) -> tuple[int, int]:
    progress = clamp01(progress)
    lengths = [math.dist(start, end) for start, end in zip(points, points[1:])]
    total = sum(lengths)
    remaining = total * progress
    cursor = points[0]
    for (start, end), length in zip(zip(points, points[1:]), lengths):
        if remaining >= length:
            draw.line((start, end), fill=color, width=width)
            cursor = end
            remaining -= length
            continue
        ratio = remaining / max(1.0, length)
        cursor = (
            round(start[0] + (end[0] - start[0]) * ratio),
            round(start[1] + (end[1] - start[1]) * ratio),
        )
        draw.line((start, cursor), fill=color, width=width)
        break
    return cursor


def make_background(size: tuple[int, int]) -> Image.Image:
    width, height = size
    image = Image.new("RGB", size, NAVY)
    draw = ImageDraw.Draw(image)
    for y in range(height):
        mix = y / max(1, height - 1)
        color = tuple(round(NAVY[i] * (1 - mix) + NAVY_2[i] * mix) for i in range(3))
        draw.line((0, y, width, y), fill=color)
    for x in range(0, width, 12):
        draw.line((x, 0, x, height), fill=(12, 31, 49))
    for y in range(0, height, 12):
        draw.line((0, y, width, y), fill=(12, 31, 49))
    draw.rounded_rectangle((1, 1, width - 2, height - 2), radius=10, outline=STEEL_LIGHT, width=1)
    return image


def estimate_background(image: Image.Image) -> tuple[int, int, int]:
    """Estimate the quiet source background from small corner samples."""
    sample = max(4, min(image.size) // 32)
    corners = (
        image.crop((0, 0, sample, sample)),
        image.crop((image.width - sample, 0, image.width, sample)),
        image.crop((0, image.height - sample, sample, image.height)),
        image.crop((image.width - sample, image.height - sample, image.width, image.height)),
    )
    values = [ImageStat.Stat(corner).median for corner in corners]
    return tuple(round(sum(value[channel] for value in values) / len(values)) for channel in range(3))


def meaningful_bounds(image: Image.Image) -> tuple[int, int, int, int]:
    """Locate the substantial foreground after the decorative border is removed."""
    background = Image.new("RGB", image.size, estimate_background(image))
    difference = ImageChops.difference(image, background).convert("L")
    mask = difference.point(lambda value: 255 if value >= 24 else 0)
    bounds = mask.getbbox()
    if bounds is None:
        return (0, 0, image.width, image.height)
    return bounds


def focus_crop(image: Image.Image, aspect: float) -> Image.Image:
    """Use one fixed crop scale per project while anchoring its central action."""
    left, top, right, bottom = meaningful_bounds(image)
    content_center_y = (top + bottom) / 2.0
    stable_center_y = content_center_y * 0.70 + (image.height / 2.0) * 0.30

    crop_width = image.width
    crop_height = round(crop_width / aspect)
    if crop_height > image.height:
        crop_height = image.height
        crop_width = round(crop_height * aspect)
    crop_left = max(0, min(image.width - crop_width, round((image.width - crop_width) / 2.0)))
    crop_top = max(0, min(image.height - crop_height, round(stable_center_y - crop_height / 2.0)))
    return image.crop((crop_left, crop_top, crop_left + crop_width, crop_top + crop_height))


def split_panels(source: Image.Image, spec: ProjectSpec) -> list[Image.Image]:
    panel_width = source.width // 4
    inset_x = max(8, round(panel_width * 0.025))
    top = max(0, round(source.height * spec.crop_y[0]))
    bottom = min(source.height, round(source.height * spec.crop_y[1]))
    panels: list[Image.Image] = []
    for index in range(4):
        left = index * panel_width + inset_x
        right = (index + 1) * panel_width - inset_x
        panel = source.crop((left, top, right, bottom)).convert("RGB")
        panels.append(focus_crop(panel, spec.focus_aspect))
    return panels


def resize_fit(image: Image.Image, max_size: tuple[int, int]) -> Image.Image:
    max_width, max_height = max_size
    scale = min(max_width / image.width, max_height / image.height)
    size = (max(1, round(image.width * scale)), max(1, round(image.height * scale)))
    return image.resize(size, Image.Resampling.NEAREST)


def dim_image(image: Image.Image, factor: float) -> Image.Image:
    return ImageEnhance.Brightness(image).enhance(factor)


def paste_panel(
    canvas: Image.Image,
    panel: Image.Image,
    center: tuple[int, int],
    max_size: tuple[int, int],
    border: tuple[int, int, int],
    brightness: float = 1.0,
) -> tuple[int, int, int, int]:
    resized = resize_fit(panel, max_size)
    if brightness != 1.0:
        resized = dim_image(resized, brightness)
    x = center[0] - resized.width // 2
    y = center[1] - resized.height // 2
    canvas.paste(resized, (x, y))
    draw = ImageDraw.Draw(canvas)
    draw.rectangle((x - 2, y - 2, x + resized.width + 1, y + resized.height + 1), outline=border, width=1)
    return (x, y, x + resized.width, y + resized.height)


def draw_signal_path(
    draw: ImageDraw.ImageDraw,
    points: Sequence[tuple[int, int]],
    color: tuple[int, int, int],
    tick: int,
    packet_count: int = 1,
) -> None:
    draw.line(points, fill=color, width=1)
    segments: list[tuple[tuple[int, int], tuple[int, int], float]] = []
    total = 0.0
    for start, end in zip(points, points[1:]):
        length = math.dist(start, end)
        segments.append((start, end, length))
        total += length
    if total <= 0:
        return
    for packet in range(packet_count):
        distance = ((tick * 8 + packet * total / packet_count) % total)
        for start, end, length in segments:
            if distance <= length:
                ratio = distance / max(1.0, length)
                x = round(start[0] + (end[0] - start[0]) * ratio)
                y = round(start[1] + (end[1] - start[1]) * ratio)
                draw.rectangle((x - 1, y - 1, x + 1, y + 1), fill=CREAM_LIGHT)
                break
            distance -= length


def draw_project_overlay(
    canvas: Image.Image,
    spec: ProjectSpec,
    stage: int,
    tick: int,
) -> None:
    draw = ImageDraw.Draw(canvas)
    pulse = (tick + stage) % 3
    accent = spec.accent
    secondary = spec.secondary

    if spec.slug == "agent-sandbox":
        draw_signal_path(draw, [(22, 151), (112, 151), (176, 140), (240, 151), (330, 151), (458, 151)], COPPER_DIM, tick, 2)
        for index in range(min(3, stage + 1)):
            x = 70 + index * 28 + ((tick + index) % 3)
            draw.rectangle((x, 154 - index * 2, x + 3, 158 - index * 2), fill=CREAM)
            draw.rectangle((x + 1, 152 - index * 2, x + 2, 153 - index * 2), fill=CYAN)
        radius = 3 + pulse
        draw.ellipse((237 - radius, 23 - radius, 237 + radius, 23 + radius), outline=CYAN, width=1)
    elif spec.slug == "mira":
        waveform = []
        for x in range(18, 462, 8):
            amplitude = 2 + stage
            y = 155 + round(math.sin((x + tick * 7) / 18) * amplitude)
            waveform.append((x, y))
        draw.line(waveform, fill=CYAN_DIM, width=1)
        for node in ((42, 40), (438, 40), (42, 116), (438, 116)):
            radius = 2 + ((pulse + node[0]) % 2)
            draw.ellipse((node[0] - radius, node[1] - radius, node[0] + radius, node[1] + radius), outline=accent)
        if stage >= 2:
            draw.arc((205, 28, 275, 98), start=200 + tick * 10, end=330 + tick * 10, fill=COPPER, width=1)
    elif spec.slug == "automata":
        paths = [
            [(34, 42), (110, 42), (180, 70), (240, 70)],
            [(446, 42), (370, 42), (300, 70), (240, 70)],
            [(34, 140), (110, 140), (180, 112), (240, 112)],
            [(446, 140), (370, 140), (300, 112), (240, 112)],
        ]
        for index, points in enumerate(paths[: min(4, stage + 1)]):
            draw_signal_path(draw, points, COPPER_DIM if index % 2 == 0 else CYAN_DIM, tick + index * 3)
        for x in (80, 400):
            draw.rectangle((x - 6, 84, x + 6, 96), outline=STEEL_LIGHT)
            if (tick + stage) % 3 == 0:
                draw.rectangle((x - 2, 88, x + 2, 92), fill=CYAN)
    else:  # spider-sense
        box = (192, 27, 288, 123)
        angle = (tick * 18 + stage * 22) % 360
        draw.arc(box, angle, angle + 70, fill=CYAN, width=1)
        draw.arc((204, 39, 276, 111), angle + 12, angle + 54, fill=CYAN_DIM, width=1)
        sources = ((44, 42), (436, 42), (44, 136), (436, 136), (240, 20))
        for index, source in enumerate(sources[: min(len(sources), stage + 2)]):
            lit = (tick + index) % 4 == 0
            draw.rectangle((source[0] - 2, source[1] - 2, source[0] + 2, source[1] + 2), fill=CREAM if lit else secondary)
            draw.line((source[0], source[1], 240, 90), fill=STEEL)


def resize_fill(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    scale = max(size[0] / image.width, size[1] / image.height)
    resized = image.resize(
        (max(1, round(image.width * scale)), max(1, round(image.height * scale))),
        Image.Resampling.NEAREST,
    )
    left = max(0, (resized.width - size[0]) // 2)
    top = max(0, (resized.height - size[1]) // 2)
    return resized.crop((left, top, left + size[0], top + size[1]))


def build_stage_base(panel: Image.Image) -> Image.Image:
    """Compose one dominant scene with a quiet plate-derived atmosphere."""
    canvas = make_background(LOGICAL_SIZE)
    atmosphere = dim_image(resize_fill(panel, LOGICAL_SIZE), 0.17)
    canvas = Image.blend(canvas, atmosphere, 0.34)
    foreground = resize_fit(panel, (322, 156))
    foreground = ImageEnhance.Brightness(foreground).enhance(1.03)
    x = (LOGICAL_SIZE[0] - foreground.width) // 2
    y = 5 + (156 - foreground.height) // 2
    canvas.paste(foreground, (x, y))
    return canvas


def draw_stage_indicator(draw: ImageDraw.ImageDraw, stage: int) -> None:
    draw.line((174, 169, 306, 169), fill=STEEL, width=1)
    for index in range(4):
        x = 195 + index * 30
        fill = CYAN if index <= stage else SURFACE
        outline = CREAM if index == stage else STEEL_LIGHT
        draw.rectangle((x - 3, 166, x + 3, 172), fill=fill, outline=outline)


def decorate_stage(
    base: Image.Image,
    spec: ProjectSpec,
    stage: int,
    tick: int,
    pulse_progress: float = 0.0,
) -> Image.Image:
    canvas = base.copy()
    draw_project_overlay(canvas, spec, stage, tick)
    draw = ImageDraw.Draw(canvas)
    phase = (tick % 6) / 5.0
    pulse = smoothstep(phase if phase <= 0.5 else 1.0 - phase) * 2.0
    pulse += max(0.0, ease_out_back(pulse_progress) - 1.0) * 2.0
    radius = 3 + round(pulse)
    draw.ellipse((240 - radius, 82 - radius, 240 + radius, 82 + radius), outline=CREAM)
    draw_stage_indicator(draw, stage)
    return canvas


def draw_transition_causality(
    canvas: Image.Image,
    spec: ProjectSpec,
    stage: int,
    progress: float,
    tick: int,
) -> None:
    draw = ImageDraw.Draw(canvas)
    eased = smoothstep(progress)
    accent = CYAN if stage % 2 == 0 else COPPER
    secondary = COPPER if accent == CYAN else CYAN

    if spec.slug == "agent-sandbox":
        inbound = [[(74, 139), (132, 122), (184, 101), (240, 82)], [(116, 151), (166, 128), (240, 82)]]
        outbound = [[(240, 82), (302, 104), (360, 128), (416, 141)], [(240, 82), (270, 118), (326, 151)]]
        routes = inbound if stage == 0 else outbound
        if stage == 2:
            routes = [[(92, 145), (158, 126), (240, 82), (322, 126), (404, 145)], [(240, 151), (240, 82), (240, 24)]]
        for index, route in enumerate(routes):
            cursor = draw_partial_path(draw, route, eased, accent if index % 2 == 0 else secondary)
            draw.rectangle((cursor[0] - 1, cursor[1] - 1, cursor[0] + 1, cursor[1] + 1), fill=CREAM_LIGHT)
        build_height = round(46 * smootherstep(progress))
        draw.rectangle((234, 132 - build_height, 246, 132), outline=COPPER if stage else CYAN)
    elif spec.slug == "mira":
        waveform: list[tuple[int, int]] = []
        extent = round(150 * eased)
        for x in range(240 - extent, 241 + extent, 6):
            y = 82 + round(math.sin((x + tick * 4) / 13.0) * (3 + stage))
            waveform.append((x, y))
        if len(waveform) > 1:
            draw.line(waveform, fill=CYAN)
        routes = [[(240, 82), (160, 44), (74, 36)], [(240, 82), (320, 44), (406, 36)], [(74, 134), (158, 118), (240, 82)], [(406, 134), (322, 118), (240, 82)]]
        for index, route in enumerate(routes):
            cursor = draw_partial_path(draw, route, eased, CYAN if index < 2 else COPPER)
            draw.rectangle((cursor[0] - 1, cursor[1] - 1, cursor[0] + 1, cursor[1] + 1), fill=CREAM_LIGHT)
        if stage >= 1:
            radius = 26 + round(32 * eased)
            draw.arc((240 - radius, 82 - radius, 240 + radius, 82 + radius), 205, 335, fill=COPPER)
    elif spec.slug == "automata":
        lanes = [[(240, 28), (240, 55), (126, 78), (80, 118)], [(240, 55), (240, 128)], [(240, 55), (354, 78), (400, 118)]]
        for index, lane in enumerate(lanes):
            cursor = draw_partial_path(draw, lane, eased, COPPER if index != 1 else CYAN)
            draw.rectangle((cursor[0] - 2, cursor[1] - 1, cursor[0] + 2, cursor[1] + 1), fill=CREAM_LIGHT)
        if stage >= 1:
            gate_x = (146, 240, 334)
            for index, x in enumerate(gate_x):
                size = 5 + round(smoothstep(progress) * 3)
                draw.rectangle((x - size, 108 - size, x + size, 108 + size), outline=CYAN if index == 1 else COPPER)
    else:  # spider-sense
        radius = 34 + stage * 11
        angle = -90 + round(300 * ease_in_out_cubic(progress))
        draw.arc((240 - radius, 82 - radius, 240 + radius, 82 + radius), -90, angle, fill=CYAN, width=1)
        sources = ((76, 38), (404, 38), (76, 138), (404, 138), (240, 20))
        for index, source in enumerate(sources):
            local_progress = smoothstep(clamp01(progress * 1.35 - index * 0.08))
            cursor = draw_partial_path(draw, [source, (240, 82)], local_progress, COPPER if index % 2 else CYAN_DIM)
            draw.rectangle((source[0] - 2, source[1] - 2, source[0] + 2, source[1] + 2), fill=CREAM if local_progress > 0.2 else STEEL)
            draw.point(cursor, fill=CREAM_LIGHT)


def transition_frame(
    spec: ProjectSpec,
    stage_bases: Sequence[Image.Image],
    stage: int,
    progress: float,
    tick: int,
    mode: str,
) -> Image.Image:
    eased = smootherstep(progress)
    composite = ordered_reveal(stage_bases[stage], stage_bases[stage + 1], eased, mode)
    visible_stage = stage if progress < 0.56 else stage + 1
    draw_project_overlay(composite, spec, visible_stage, tick)
    draw_transition_causality(composite, spec, stage, progress, tick)
    draw_stage_indicator(ImageDraw.Draw(composite), visible_stage)
    return composite


def spark_frame(spec: ProjectSpec, tick: int = 0) -> Image.Image:
    canvas = make_background(LOGICAL_SIZE)
    draw = ImageDraw.Draw(canvas)
    phase = (tick % 6) / 5.0
    radius = 3 + round(smoothstep(phase if phase <= 0.5 else 1.0 - phase) * 3)
    draw.ellipse((240 - radius, 82 - radius, 240 + radius, 82 + radius), outline=spec.accent, width=1)
    draw.rectangle((238, 80, 242, 84), fill=CREAM)
    draw.line((240, 20, 240, 73), fill=STEEL)
    draw.line((240, 92, 240, 158), fill=STEEL)
    for offset in (-2, -1, 1, 2):
        draw.rectangle((240 + offset * 18, 81, 242 + offset * 18, 83), fill=spec.secondary)
    return canvas


def reset_frame(
    spec: ProjectSpec,
    final_frame: Image.Image,
    spark: Image.Image,
    progress: float,
    tick: int,
) -> Image.Image:
    eased = smootherstep(progress)
    canvas = ordered_reveal(final_frame, spark, eased, "edge_in")
    if progress >= 0.999:
        return spark.copy()
    draw = ImageDraw.Draw(canvas)
    inverse = 1.0 - smoothstep(progress)
    if spec.slug == "agent-sandbox":
        draw_partial_path(draw, [(84, 145), (240, 82), (240, 20)], 1.0 - inverse * 0.35, CYAN)
    elif spec.slug == "mira":
        extent = max(4, round(180 * inverse))
        points = [(x, 82 + round(math.sin((x + tick * 3) / 12.0) * 4 * inverse)) for x in range(240 - extent, 241 + extent, 6)]
        if len(points) > 1:
            draw.line(points, fill=CYAN)
    elif spec.slug == "automata":
        for start in ((74, 36), (406, 36), (74, 140), (406, 140)):
            draw_partial_path(draw, [start, (240, 82)], eased, COPPER)
    else:
        radius = max(4, round(74 * inverse))
        draw.ellipse((240 - radius, 82 - radius, 240 + radius, 82 + radius), outline=CYAN)
    radius = max(2, round(10 * inverse))
    draw.ellipse((240 - radius, 82 - radius, 240 + radius, 82 + radius), outline=CREAM)
    return canvas


def upscale(frame: Image.Image, size: tuple[int, int]) -> Image.Image:
    return frame.resize(size, Image.Resampling.NEAREST)


def fixed_palette(frames: Sequence[Image.Image], colors: int) -> Image.Image:
    sample_width = 240
    sample_height = 90
    columns = 4
    rows = math.ceil(len(frames) / columns)
    atlas = Image.new("RGB", (sample_width * columns, sample_height * rows), NAVY)
    for index, frame in enumerate(frames):
        thumb = frame.resize((sample_width, sample_height), Image.Resampling.NEAREST)
        atlas.paste(thumb, ((index % columns) * sample_width, (index // columns) * sample_height))
    return atlas.quantize(colors=colors, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)


def save_gif(
    frames: Sequence[Image.Image],
    durations: Sequence[int],
    output: Path,
    colors: int,
    optimize: bool = True,
) -> None:
    palette = fixed_palette(frames, colors)
    quantized = [
        frame.quantize(palette=palette, dither=Image.Dither.NONE)
        for frame in frames
    ]
    output.parent.mkdir(parents=True, exist_ok=True)
    quantized[0].save(
        output,
        save_all=True,
        append_images=quantized[1:],
        duration=list(durations),
        loop=0,
        optimize=optimize,
        disposal=1,
    )


def build_project_animation(
    spec: ProjectSpec,
    source_path: Path,
    output_dir: Path,
    colors: int,
) -> dict[str, object]:
    source = Image.open(source_path).convert("RGB")
    if source.width < 1600 or source.height < 600 or not (2.8 <= source.width / source.height <= 3.2):
        raise ValueError(
            f"{source_path}: expected a high-resolution four-panel plate near 3:1, "
            f"got {source.size[0]}x{source.size[1]}"
        )
    panels = split_panels(source, spec)
    stage_bases = [build_stage_base(panel) for panel in panels]

    poster_logical = decorate_stage(stage_bases[3], spec, 3, 5)
    spark = spark_frame(spec)

    logical_frames: list[Image.Image] = [poster_logical]
    durations: list[int] = [100 + spec.offset_ms]

    # Dedicated thematic loop reset: the completed system contracts into its seed.
    for index in range(10):
        progress = (index + 1) / 10.0
        logical_frames.append(reset_frame(spec, poster_logical, spark, progress, index))
        durations.append(80)

    # The seed activates into the first inspectable state through a coherent radial reveal.
    for index in range(6):
        progress = (index + 1) / 6.0
        frame = ordered_reveal(spark, stage_bases[0], smootherstep(progress), "center_out")
        if progress < 1.0:
            draw_transition_causality(frame, spec, 0, progress * 0.45, index)
        logical_frames.append(frame)
        durations.append(80)

    for tick in range(4):
        logical_frames.append(decorate_stage(stage_bases[0], spec, 0, tick))
        durations.append(100)

    for stage in range(3):
        mode = TRANSITION_MODES[spec.slug][stage]

        # Anticipation: route signals toward the elements that will produce the next state.
        for index in range(4):
            progress = (index + 1) / 4.0
            frame = decorate_stage(stage_bases[stage], spec, stage, index)
            draw_transition_causality(frame, spec, stage, progress * 0.24, index)
            logical_frames.append(frame)
            durations.append(90)

        # Bridge: an ordered, project-specific causal field reveals the next stage.
        for index in range(8):
            progress = (index + 1) / 8.0
            logical_frames.append(transition_frame(spec, stage_bases, stage, progress, index, mode))
            durations.append(80)

        # Resolution: settle the new geometry and pulse the newly activated core once.
        for index in range(4):
            progress = (index + 1) / 4.0
            frame = decorate_stage(stage_bases[stage + 1], spec, stage + 1, index, pulse_progress=progress)
            if progress < 1.0:
                draw_transition_causality(frame, spec, stage, 1.0, index + 8)
            logical_frames.append(frame)
            durations.append(100)

        # Hold: preserve only restrained ambient motion so the new state can be read.
        for index in range(6):
            logical_frames.append(decorate_stage(stage_bases[stage + 1], spec, stage + 1, index + 4))
            durations.append(100)

    logical_frames.append(poster_logical)
    durations.append(2500 - spec.offset_ms)

    if len(logical_frames) != 88:
        raise AssertionError(f"{spec.slug}: expected 88 frames, got {len(logical_frames)}")
    if sum(durations) != 10280:
        raise AssertionError(f"{spec.slug}: expected 10280 ms, got {sum(durations)}")

    frames = [upscale(frame, OUTPUT_SIZE) for frame in logical_frames]
    poster = frames[0]
    gif_path = output_dir / f"{spec.slug}.gif"
    poster_path = output_dir / f"{spec.slug}-poster.png"
    poster.save(poster_path, format="PNG", optimize=True)
    save_gif(frames, durations, gif_path, colors=colors)

    return {
        "kind": "project",
        "slug": spec.slug,
        "source": source_path.name,
        "source_sha256": sha256_file(source_path),
        "gif": str(gif_path.relative_to(output_dir.parent.parent)).replace("\\", "/"),
        "poster": str(poster_path.relative_to(output_dir.parent.parent)).replace("\\", "/"),
        "width": OUTPUT_SIZE[0],
        "height": OUTPUT_SIZE[1],
        "frames": len(frames),
        "duration_ms": sum(durations),
        "file_size": gif_path.stat().st_size,
        "sha256": sha256_file(gif_path),
        "alt": spec.alt,
    }


def glyph_background() -> Image.Image:
    image = make_background(GLYPH_LOGICAL_SIZE)
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((2, 2, 45, 45), radius=6, outline=STEEL_LIGHT, width=1)
    return image


def draw_gate(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], color: tuple[int, int, int]) -> None:
    x1, y1, x2, y2 = box
    draw.rectangle((x1, y1, x2, y2), outline=color, width=1)
    draw.rectangle((x1 + 3, y1 + 3, x2 - 3, y2 - 3), outline=STEEL)


def glyph_frame(kind: str, tick: int) -> Image.Image:
    image = glyph_background()
    draw = ImageDraw.Draw(image)
    active = tick % 8

    if kind == "authority":
        draw.line((5, 24, 18, 24), fill=COPPER_DIM)
        draw.line((30, 24, 43, 24), fill=CYAN_DIM)
        draw.line((24, 30, 24, 40), fill=STEEL)
        draw.rectangle((21, 38, 27, 42), outline=COPPER_DIM)
        draw_gate(draw, (18, 16, 30, 30), CREAM)
        proposal_x = min(17, 6 + active * 2)
        draw.rectangle((proposal_x, 21, proposal_x + 3, 25), fill=COPPER)
        if active >= 5:
            pulse_x = min(40, 31 + (active - 5) * 4)
            draw.rectangle((pulse_x, 21, pulse_x + 3, 25), fill=CYAN)
    elif kind == "evidence":
        sources = ((8, 10), (8, 24), (8, 38))
        for index, (x, y) in enumerate(sources):
            lit = active >= index * 2
            color = CYAN if lit else STEEL
            draw.rectangle((x - 2, y - 2, x + 2, y + 2), fill=color)
            draw.line((x + 3, y, 31, 24), fill=CYAN_DIM if lit else STEEL)
        draw.polygon(((34, 15), (42, 24), (34, 33), (26, 24)), outline=CREAM, fill=SURFACE)
        if active >= 6:
            draw.rectangle((33, 22, 35, 25), fill=CYAN)
    elif kind == "agency":
        draw.ellipse((8, 8, 40, 40), outline=CYAN, width=1)
        draw.arc((11, 11, 37, 37), 35, 145, fill=CREAM, width=1)
        for angle in (20, 140, 260):
            radians = math.radians(angle)
            x = round(24 + math.cos(radians) * 18)
            y = round(24 + math.sin(radians) * 18)
            draw.rectangle((x - 1, y - 1, x + 1, y + 1), fill=COPPER)
        path = ((16, 30), (20, 25), (24, 22), (28, 25), (32, 19))
        index = min(len(path) - 1, active // 2)
        x, y = path[index]
        draw.rectangle((x - 2, y - 2, x + 2, y + 2), fill=CREAM)
        draw.rectangle((x - 1, y - 1, x + 1, y + 1), fill=CYAN)
    elif kind == "emergence":
        nodes = ((24, 35), (16, 27), (32, 27), (12, 18), (24, 15), (36, 18))
        visible = min(len(nodes), 2 + active)
        for index, node in enumerate(nodes[:visible]):
            if index > 0:
                parent = nodes[(index - 1) // 2]
                draw.line((parent[0], parent[1], node[0], node[1]), fill=CYAN_DIM if index % 2 else COPPER_DIM)
            draw.rectangle((node[0] - 2, node[1] - 2, node[0] + 2, node[1] + 2), fill=CYAN if index % 2 else COPPER)
        if active >= 6:
            draw.line((12, 18, 12, 10, 20, 10), fill=CREAM)
            draw.line((36, 18, 36, 10, 28, 10), fill=CREAM)
            draw.rectangle((22, 8, 26, 12), fill=CREAM)
    else:  # boundaries
        center = (24, 24)
        shapes = []
        for index, angle in enumerate((270, 342, 54, 126, 198)):
            radians = math.radians(angle + active * 2)
            x = round(center[0] + math.cos(radians) * 16)
            y = round(center[1] + math.sin(radians) * 16)
            shapes.append((x, y))
            draw.line((center[0], center[1], x, y), fill=STEEL)
            if index == 0:
                draw.rectangle((x - 2, y - 2, x + 2, y + 2), outline=CYAN)
            elif index == 1:
                draw.rectangle((x - 3, y - 2, x + 3, y), fill=COPPER)
                draw.line((x - 3, y + 2, x + 3, y + 2), fill=COPPER)
            elif index == 2:
                draw.polygon(((x, y - 3), (x + 3, y), (x, y + 3), (x - 3, y)), outline=CREAM)
            elif index == 3:
                draw.line((x - 3, y, x + 3, y), fill=CYAN)
                draw.line((x, y - 3, x, y + 3), fill=CYAN)
            else:
                draw.polygon(((x, y - 3), (x + 3, y - 1), (x + 2, y + 3), (x, y + 4), (x - 2, y + 3), (x - 3, y - 1)), outline=COPPER)
        draw.rectangle((22, 22, 26, 26), fill=CREAM)
    # A quiet ten-position clock keeps every authored frame distinct without
    # competing with the glyph itself or introducing visible flicker.
    clock_x = 4 + (tick % 10) * 4
    draw.point((clock_x, 44), fill=CYAN_DIM if tick % 2 == 0 else COPPER_DIM)
    return image


def build_glyph_animation(kind: str, output_dir: Path, colors: int) -> dict[str, object]:
    frames_logical = [glyph_frame(kind, tick) for tick in range(10)]
    poster_logical = glyph_frame(kind, 7)
    frames_logical[0] = poster_logical
    frames = [upscale(frame, GLYPH_OUTPUT_SIZE) for frame in frames_logical]
    poster = upscale(poster_logical, GLYPH_OUTPUT_SIZE)

    leading = GLYPH_OFFSETS[kind]
    active_durations = [120] * 8
    trailing = 6000 - leading - sum(active_durations)
    durations = [leading] + active_durations + [trailing]

    gif_path = output_dir / f"{kind}.gif"
    poster_path = output_dir / f"{kind}-poster.png"
    poster.save(poster_path, format="PNG", optimize=True)
    save_gif(frames, durations, gif_path, colors=colors, optimize=False)
    return {
        "kind": "principle",
        "slug": kind,
        "source": "procedural",
        "gif": str(gif_path.relative_to(output_dir.parent.parent.parent)).replace("\\", "/"),
        "poster": str(poster_path.relative_to(output_dir.parent.parent.parent)).replace("\\", "/"),
        "width": GLYPH_OUTPUT_SIZE[0],
        "height": GLYPH_OUTPUT_SIZE[1],
        "frames": len(frames),
        "duration_ms": sum(durations),
        "file_size": gif_path.stat().st_size,
        "sha256": sha256_file(gif_path),
        "alt": GLYPH_ALTS[kind],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agent-sandbox", dest="agent_sandbox", type=Path, required=True)
    parser.add_argument("--mira", type=Path, required=True)
    parser.add_argument("--automata", type=Path, required=True)
    parser.add_argument("--spider-sense", dest="spider_sense", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--project-colors", type=int, default=48)
    parser.add_argument("--glyph-colors", type=int, default=24)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    repo_root = Path(__file__).resolve().parents[1]
    output_dir = args.output_dir or (repo_root / "assets" / "animations")
    principles_dir = output_dir / "principles"
    output_dir.mkdir(parents=True, exist_ok=True)
    principles_dir.mkdir(parents=True, exist_ok=True)

    assets: list[dict[str, object]] = []
    for spec in PROJECTS:
        source_path = getattr(args, spec.source_arg).resolve()
        if not source_path.is_file():
            raise FileNotFoundError(source_path)
        assets.append(build_project_animation(spec, source_path, output_dir, args.project_colors))

    for kind in ("authority", "evidence", "agency", "emergence", "boundaries"):
        assets.append(build_glyph_animation(kind, principles_dir, args.glyph_colors))

    manifest = {
        "version": 1,
        "seed_namespace": SEED_NAMESPACE,
        "project_palette_colors": args.project_colors,
        "principle_palette_colors": args.glyph_colors,
        "assets": assets,
        "total_gif_bytes": sum(int(asset["file_size"]) for asset in assets),
    }
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(f"Built {len(assets)} animated assets")
    for asset in assets:
        print(
            f"{asset['slug']:>16}  {asset['width']}x{asset['height']}  "
            f"{asset['frames']:>2} frames  {asset['duration_ms'] / 1000:>4.1f}s  "
            f"{asset['file_size'] / 1024:>7.1f} KiB"
        )
    print(f"Total GIF weight: {manifest['total_gif_bytes'] / 1024 / 1024:.2f} MiB")


if __name__ == "__main__":
    main()
