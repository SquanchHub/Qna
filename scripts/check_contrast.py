#!/usr/bin/env python3
"""
Check the T8 color tokens against WCAG 2.1 AA contrast in both themes.

Parses frontend/shared/tokens.css (the light block and the explicit
[data-theme='dark'] block), checks that the prefers-color-scheme dark
fallback matches the explicit dark block, then computes the contrast ratio
for every text/background pair the apps actually render:

  - text tokens on each surface                       (>= 4.5:1)
  - badge text on its own 10% tint over a surface     (>= 4.5:1)
  - accent-contrast on accent and danger fills,
    including the 90% hover fill                      (>= 4.5:1)
  - border-strong and focus-ring against surfaces     (>= 3:1, WCAG 1.4.11)

The decorative `border` token is reported but not held to 3:1; inputs and
outline buttons use border-strong instead.

Usage:
    python scripts/check_contrast.py              # table per theme
    python scripts/check_contrast.py --markdown   # markdown tables for docs

Exits 1 if any checked pair falls below its threshold.
"""

import argparse
import re
import sys
from pathlib import Path

TOKENS_CSS = (
    Path(__file__).resolve().parent.parent / "frontend" / "shared" / "tokens.css"
)

SURFACES = ["surface", "surface-raised", "surface-sunken"]
TEXT_TOKENS = [
    "text-primary",
    "text-secondary",
    "text-muted",
    "accent",
    "danger",
    "success",
    "warning",
    "info",
    "ai",
]
# Badge variants render `bg-<token>/10 text-<token>` (components/ui/badge.tsx).
CHIP_TOKENS = ["accent", "danger", "success", "warning", "info", "ai"]
CHIP_ALPHA = 0.10
CHIP_BACKGROUNDS = ["surface", "surface-raised"]
# Filled buttons: bg-<fill> text-accent-contrast, hover:bg-<fill>/90.
FILLS = ["accent", "danger"]
HOVER_ALPHA = 0.90

TEXT_MIN = 4.5
NON_TEXT_MIN = 3.0

RGB = tuple[int, int, int]


def parse_block(css: str, selector_pattern: str) -> dict[str, RGB]:
    match = re.search(selector_pattern + r"\s*\{([^}]*)\}", css, flags=re.M)
    if not match:
        sys.exit(
            f"Could not find a block matching {selector_pattern!r} in {TOKENS_CSS}"
        )
    return {
        name: (int(r), int(g), int(b))
        for name, r, g, b in re.findall(
            r"--color-([\w-]+):\s*(\d+)\s+(\d+)\s+(\d+)\s*;", match.group(1)
        )
    }


def load_themes() -> dict[str, dict[str, RGB]]:
    css = re.sub(r"/\*.*?\*/", "", TOKENS_CSS.read_text(), flags=re.S)
    light = parse_block(css, r"\[data-theme='light'\]")
    dark = parse_block(css, r"^\[data-theme='dark'\]")
    fallback = parse_block(css, r":root:not\(\[data-theme='light'\]\)")
    if fallback != dark:
        drift = sorted(
            k for k in dark.keys() | fallback.keys() if dark.get(k) != fallback.get(k)
        )
        sys.exit(
            f"prefers-color-scheme dark fallback differs from [data-theme='dark']: {drift}"
        )
    if light.keys() != dark.keys():
        sys.exit(
            f"Themes define different tokens: {sorted(light.keys() ^ dark.keys())}"
        )
    return {"light": light, "dark": dark}


def luminance(c: RGB) -> float:
    def channel(v: int) -> float:
        s = v / 255
        return s / 12.92 if s <= 0.04045 else ((s + 0.055) / 1.055) ** 2.4

    r, g, b = (channel(v) for v in c)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: RGB, b: RGB) -> float:
    hi, lo = sorted((luminance(a), luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def blend(fg: RGB, bg: RGB, alpha: float) -> RGB:
    return tuple(round(f * alpha + b * (1 - alpha)) for f, b in zip(fg, bg))  # type: ignore[return-value]


def check_theme(t: dict[str, RGB]) -> list[tuple[str, str, str, float, float | None]]:
    """Return (group, foreground, background, ratio, threshold) rows; threshold None = informational."""
    rows: list[tuple[str, str, str, float, float | None]] = []
    for fg in TEXT_TOKENS:
        for bg in SURFACES:
            rows.append(("text", fg, bg, contrast(t[fg], t[bg]), TEXT_MIN))
    for fg in CHIP_TOKENS:
        for bg in CHIP_BACKGROUNDS:
            chip = blend(t[fg], t[bg], CHIP_ALPHA)
            rows.append(
                ("badge", fg, f"{fg}/10 on {bg}", contrast(t[fg], chip), TEXT_MIN)
            )
    for fill in FILLS:
        rows.append(
            (
                "fill",
                "accent-contrast",
                fill,
                contrast(t["accent-contrast"], t[fill]),
                TEXT_MIN,
            )
        )
        hover = blend(t[fill], t["surface"], HOVER_ALPHA)
        rows.append(
            (
                "fill",
                "accent-contrast",
                f"{fill}/90 on surface",
                contrast(t["accent-contrast"], hover),
                TEXT_MIN,
            )
        )
    for fg in ["border-strong", "focus-ring"]:
        for bg in SURFACES:
            rows.append(("non-text", fg, bg, contrast(t[fg], t[bg]), NON_TEXT_MIN))
    for bg in SURFACES:
        rows.append(("decorative", "border", bg, contrast(t["border"], t[bg]), None))
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--markdown", action="store_true", help="print markdown tables")
    args = parser.parse_args()

    failures = 0
    for name, theme in load_themes().items():
        rows = check_theme(theme)
        if args.markdown:
            print(f"### {name.capitalize()} theme\n")
            print("| Group | Foreground | Background | Ratio | Min | Result |")
            print("|---|---|---|---|---|---|")
        else:
            print(f"== {name}")
        for group, fg, bg, ratio, minimum in rows:
            ok = minimum is None or ratio >= minimum
            failures += not ok
            result = "info" if minimum is None else ("pass" if ok else "FAIL")
            min_str = "—" if minimum is None else f"{minimum:.1f}"
            if args.markdown:
                print(
                    f"| {group} | `{fg}` | `{bg}` | {ratio:.2f} | {min_str} | {result} |"
                )
            else:
                print(
                    f"  {group:<10} {fg:<16} on {bg:<28} {ratio:6.2f}  (min {min_str})  {result}"
                )
        print()

    if failures:
        print(f"{failures} pair(s) below WCAG AA.")
        return 1
    print("All checked pairs meet WCAG AA.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
