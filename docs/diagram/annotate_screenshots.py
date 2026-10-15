"""Crop, label and frame the demo screenshots for the README.

Run from the repo root:
    uv run --with pillow python docs/diagram/annotate_screenshots.py

Reads the originals in docs/screenshots/ (never modified) and writes labeled, framed copies to
docs/images/. Coordinates are in original-image pixels. Each mark is a numbered box plus a tag.
"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

SRC, OUT = Path("docs/screenshots"), Path("docs/images")
OUT.mkdir(parents=True, exist_ok=True)
FONT = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 22)
RED, GREEN, AMBER = (248, 81, 73), (46, 194, 96), (255, 184, 0)
# Frame: a light mat with a mid-gray border, so dark screenshots don't blend into GitHub's
# dark theme and still stand apart from the white page in the light theme.
MAT, BORDER, MAT_PAD, BORDER_W, RADIUS = (234, 238, 242), (140, 149, 159), 14, 3, 18


def frame(img: Image.Image) -> Image.Image:
    w, h = img.width + 2 * MAT_PAD, img.height + 2 * MAT_PAD
    out = Image.new("RGBA", (w, h), (0, 0, 0, 0))  # transparent outside the rounded corners
    d = ImageDraw.Draw(out)
    d.rounded_rectangle((0, 0, w - 1, h - 1), radius=RADIUS, fill=MAT, outline=BORDER, width=BORDER_W)
    out.paste(img, (MAT_PAD, MAT_PAD))
    d.rectangle(  # hairline around the screenshot itself
        (MAT_PAD - 1, MAT_PAD - 1, MAT_PAD + img.width, MAT_PAD + img.height), outline=BORDER, width=1
    )
    return out


def tag(draw, xy, text, color, anchor="above"):
    """Caption tag next to a box: dark text on a colored pill."""
    x0, y0, x1, y1 = xy
    tw, th = draw.textbbox((0, 0), text, font=FONT)[2:]
    pad = 8
    w, h = tw + 2 * pad, th + 2 * pad
    if anchor == "above":
        tx, ty = x0, y0 - h - 6
    elif anchor == "above_right":  # right-aligned with the box, for boxes near the right edge
        tx, ty = x1 - w, y0 - h - 6
    elif anchor == "below":
        tx, ty = x0, y1 + 6
    elif anchor == "right":
        tx, ty = x1 + 10, (y0 + y1) // 2 - h // 2
    else:  # inside, top-right corner
        tx, ty = x1 - w - 6, y0 + 6
    draw.rounded_rectangle((tx, ty, tx + w, ty + h), radius=8, fill=color)
    draw.text((tx + pad, ty + pad - 2), text, font=FONT, fill=(13, 17, 23))


def mark(draw, box, n, text, color, anchor="above"):
    draw.rounded_rectangle(box, radius=6, outline=color, width=4)
    tag(draw, box, f"{n}  {text}", color, anchor)


def make(name, out, marks, crop=None, pad_top=0, pad_right=0):
    img = Image.open(SRC / name).convert("RGB")
    cx, cy = (crop[0], crop[1]) if crop else (0, 0)  # boxes are in original pixels; shift into the crop
    if crop:
        img = img.crop(crop)
    if pad_top or pad_right:  # dark margin so tags don't cover the content they point at
        canvas = Image.new("RGB", (img.width + pad_right, img.height + pad_top), (13, 17, 23))
        canvas.paste(img, (0, pad_top))
        img = canvas
    draw = ImageDraw.Draw(img)
    for box, n, text, color, anchor in marks:
        x0, y0, x1, y1 = box
        mark(draw, (x0 - cx, y0 - cy + pad_top, x1 - cx, y1 - cy + pad_top), n, text, color, anchor)
    img = frame(img)
    img.save(OUT / out, optimize=True)
    print(out, img.size)


# 1. The change: PR #4 diff
make("04-break-pr-diff.png", "demo-1-break-diff.png", [
    ((210, 346, 450, 402), "1", "prompt version bumped v1 → v2", AMBER, "right"),
    ((210, 534, 850, 588), "2", "refund rule replaced: never check the policy", RED, "below"),
], crop=(60, 170, 1620, 720))

# 2. CI starts: required check, merge disabled
make("05-ci-running.png", "demo-2-ci-running.png", [
    ((1012, 148, 1112, 184), "1", "eval is a required check", AMBER, "above_right"),
    ((116, 268, 368, 320), "2", "merge disabled until it passes", AMBER, "right"),
], pad_top=0)

# 3. CI goes red: the PR comment
make("07-pr-comment-fail.png", "demo-3-pr-comment-fail.png", [
    ((196, 104, 610, 146), "1", "verdict", RED, "right"),
    ((204, 168, 1030, 496), "2", "why it failed", RED, "right"),
    ((198, 560, 815, 604), "3", "74.7% → 28.0%", RED, "right"),
    ((186, 1270, 620, 1342), "4", "required check failed", RED, "right"),
], crop=(90, 20, 1288, 1416), pad_top=0)

# 4. Failing cases with trace IDs
make("08-pr-comment-failing-cases.png", "demo-4-failing-cases.png", [
    ((70, 232, 1100, 330), "1", "refunded, never checked policy", RED, "right"),
    ((540, 50, 640, 92), "2", "trace ID per case", AMBER, "right"),
], crop=(50, 0, 1110, 600), pad_right=440)

# 5. The workflow run
make("09-actions-run-steps.png", "demo-5-actions-run.png", [
    ((24, 500, 2318, 542), "1", "evals ran (exit code saved, comment + traces still posted)", AMBER, "inside"),
    ((24, 655, 2318, 800), "2", "last step fails the job: rgate exited with code 1", RED, "inside"),
], crop=(0, 0, 2340, 980))

# 6. The fix diff
make("13-fix-diff.png", "demo-6-fix-diff.png", [
    ((118, 145, 355, 208), "1", "v2 → v3", GREEN, "right"),
    ((130, 369, 1080, 432), "2", "refund rule restored", GREEN, "right"),
], crop=(0, 78, 1500, 584))

# 7. CI green again: same comment, edited
make("15-pr-comment-pass.png", "demo-7-pr-comment-pass.png", [
    ((114, 84, 540, 130), "1", "verdict", GREEN, "right"),
    ((548, 26, 648, 58), "2", "same comment, edited", GREEN, "right"),
    ((122, 200, 738, 246), "3", "77.3%, +2.7 vs baseline", GREEN, "right"),
    ((110, 1000, 560, 1058), "4", "required check passed", GREEN, "right"),
    ((118, 1182, 366, 1232), "5", "merge enabled", GREEN, "right"),
])

# 8. Run history
make("16-actions-history.png", "demo-8-actions-history.png", [
    ((20, 88, 535, 156), "1", "PR opened: red", RED, "right"),
    ((20, 2, 535, 70), "2", "fix pushed: green", GREEN, "right"),
], pad_top=0)

# Setup screenshots: no labels, just the frame.
make("01-repo-secret.png", "setup-1-repo-secret.png", [])
make("02-branch-protection.png", "setup-2-branch-protection.png", [])
make("03-ci-merged-pr.png", "setup-3-first-ci-pr.png", [], crop=(0, 0, 1236, 780))
