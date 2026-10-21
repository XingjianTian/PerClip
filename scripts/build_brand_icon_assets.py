#!/usr/bin/env python3
"""Build PerClip icon assets from the user-supplied 1254 px pixel masters.

The light and dark PNGs are the visual authority.  They are resized directly
for legacy launchers, while the extracted SVG contour is retained for alpha-
only Android surfaces such as themed and notification icons.
"""

from __future__ import annotations

import argparse
import base64
import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REFERENCE = ROOT / "docs/ui-discovery/assets/app-icon-v2/reference"
LIGHT_MASTER = REFERENCE / "app-icon-light-1254.png"
DARK_MASTER = REFERENCE / "app-icon-dark-1254.png"
CONTOUR_MASTER = REFERENCE / "mark-contour-1254.svg"


def embedded_png_svg(source: Path) -> str:
    payload = base64.b64encode(source.read_bytes()).decode("ascii")
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="1254" height="1254" viewBox="0 0 1254 1254">
  <image width="1254" height="1254" href="data:image/png;base64,{payload}"/>
</svg>
'''


def recolored_contour(color: str) -> str:
    svg = CONTOUR_MASTER.read_text(encoding="utf-8")
    return svg.replace('fill="#000000"', f'fill="{color}"')


def resize(source: Path, destination: Path, size: int) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "magick",
            str(source),
            "-filter",
            "Lanczos",
            "-resize",
            f"{size}x{size}",
            str(destination),
        ],
        check=True,
    )


def write_review_sources(output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    (output / "app-icon-light.svg").write_text(embedded_png_svg(LIGHT_MASTER), encoding="utf-8")
    (output / "app-icon-dark.svg").write_text(embedded_png_svg(DARK_MASTER), encoding="utf-8")
    (output / "brand-mark-only.svg").write_text(recolored_contour("#B683F2"), encoding="utf-8")
    (output / "notification-small-icon.svg").write_text(recolored_contour("#FFFFFF"), encoding="utf-8")
    resize(DARK_MASTER, output / "play-store-512.png", 512)


def write_android_fallbacks(res: Path) -> None:
    densities = {"mdpi": 48, "hdpi": 72, "xhdpi": 96, "xxhdpi": 144, "xxxhdpi": 192}
    for density, size in densities.items():
        for mode, source in (("", LIGHT_MASTER), ("night-", DARK_MASTER)):
            destination = res / f"mipmap-{mode}{density}"
            resize(source, destination / "ic_launcher.png", size)
            resize(source, destination / "ic_launcher_round.png", size)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument("--android-res", type=Path)
    args = parser.parse_args()
    if shutil.which("magick") is None:
        raise SystemExit("ImageMagick (magick) is required")
    for source in (LIGHT_MASTER, DARK_MASTER, CONTOUR_MASTER):
        if not source.exists():
            raise SystemExit(f"missing pixel-reference source: {source}")
    write_review_sources(args.output)
    if args.android_res:
        write_android_fallbacks(args.android_res)


if __name__ == "__main__":
    main()
