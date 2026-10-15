"""Draw the end-to-end RegressionGate flowchart (black and white, with service logos).

Run from the repo root:
    uv run --with cairosvg python docs/diagram/build_flowchart.py

Writes docs/images/flowchart.svg and docs/images/flowchart.png. Layout is hand-placed
(coordinates below) so arrows stay straight and nothing overlaps. Logos are from
Simple Icons (CC0); the trademarks belong to their owners.
"""

import re
from html import escape
from pathlib import Path

from PIL import ImageFont

HERE = Path(__file__).parent
ICONS = HERE / "icons"
OUT = HERE.parent / "images"

FONT_FAMILY = "DejaVu Sans"
FONT_FILES = {
    False: "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    True: "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
}
W, H = 1840, 2880
BAND_RIGHT = 1770  # sections end here; the loop-back line runs in the margin to the right
INK, SOFT, PAPER = "#000000", "#4a4a4a", "#ffffff"
TITLE_SIZE, BODY_SIZE, PAD, ICON = 17, 14, 16, 26

svg: list[str] = []
_fonts: dict = {}


def text_width(text: str, size: int, bold: bool = False) -> float:
    key = (size, bold)
    if key not in _fonts:
        _fonts[key] = ImageFont.truetype(FONT_FILES[bold], size)
    return _fonts[key].getlength(text)


def text(x, y, s, size=BODY_SIZE, bold=False, color=INK, anchor="start"):
    weight = "bold" if bold else "normal"
    svg.append(
        f'<text x="{x}" y="{y}" font-family="{FONT_FAMILY}" font-size="{size}" font-weight="{weight}" '
        f'fill="{color}" text-anchor="{anchor}">{escape(s)}</text>'
    )


def icon(name, x, y, size=ICON, color=INK):
    d = re.search(r'<path d="([^"]+)"', (ICONS / f"{name}.svg").read_text()).group(1)
    svg.append(f'<svg x="{x}" y="{y}" width="{size}" height="{size}" viewBox="0 0 24 24"><path d="{d}" fill="{color}"/></svg>')


def check_fits(lines, width, title, has_icons):
    """Fail loudly if a line would overflow its box, instead of shipping a clipped diagram."""
    room = width - 2 * PAD
    t_room = room - (ICON + 10) * has_icons
    if text_width(title, TITLE_SIZE, True) > t_room:
        raise SystemExit(f"title too wide: {title!r}")
    for line in lines:
        if text_width(line, BODY_SIZE) > room:
            raise SystemExit(f"line too wide in {title!r}: {line!r}")


def box(x, y, w, h, title, lines=(), icons=(), dashed=False, fill=PAPER, shape="rect"):
    """A process box: logos + bold title on the first row, body lines below."""
    dash = ' stroke-dasharray="7 5"' if dashed else ""
    if shape == "doc":  # document: folded top-right corner
        f = 18
        svg.append(
            f'<path d="M{x},{y} H{x + w - f} L{x + w},{y + f} V{y + h} H{x} Z" fill="{fill}" '
            f'stroke="{INK}" stroke-width="2"{dash}/>'
        )
        svg.append(f'<path d="M{x + w - f},{y} V{y + f} H{x + w}" fill="none" stroke="{INK}" stroke-width="2"/>')
    else:
        svg.append(
            f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="10" fill="{fill}" stroke="{INK}" '
            f'stroke-width="2"{dash}/>'
        )
    check_fits(lines, w, title, len(icons) > 0)
    tx = x + PAD
    for name in icons:
        icon(name, tx, y + 12)
        tx += ICON + 8
    text(tx + (2 if icons else 0), y + 31, title, TITLE_SIZE, bold=True)
    for i, line in enumerate(lines):
        text(x + PAD, y + 58 + i * 21, line, BODY_SIZE, color=SOFT)


def cylinder(x, y, w, h, title, lines=(), icons=()):
    """A database."""
    ry = 14
    svg.append(
        f'<path d="M{x},{y + ry} V{y + h - ry} A{w / 2},{ry} 0 0 0 {x + w},{y + h - ry} V{y + ry}" '
        f'fill="{PAPER}" stroke="{INK}" stroke-width="2"/>'
    )
    svg.append(f'<ellipse cx="{x + w / 2}" cy="{y + ry}" rx="{w / 2}" ry="{ry}" fill="{PAPER}" stroke="{INK}" stroke-width="2"/>')
    check_fits(lines, w, title, len(icons) > 0)
    tx = x + PAD
    for name in icons:
        icon(name, tx, y + 32)
        tx += ICON + 8
    text(tx + 2, y + 51, title, TITLE_SIZE, bold=True)
    for i, line in enumerate(lines):
        text(x + PAD, y + 77 + i * 21, line, BODY_SIZE, color=SOFT)


def diamond(cx, cy, w, h, title, lines=()):
    """A decision."""
    pts = f"{cx},{cy - h / 2} {cx + w / 2},{cy} {cx},{cy + h / 2} {cx - w / 2},{cy}"
    svg.append(f'<polygon points="{pts}" fill="{PAPER}" stroke="{INK}" stroke-width="2.5"/>')
    total = 1 + len(lines)
    y0 = cy - (total - 1) * 10 + 5
    text(cx, y0, title, 16, bold=True, anchor="middle")
    for i, line in enumerate(lines):
        text(cx, y0 + 21 * (i + 1), line, 13, color=SOFT, anchor="middle")


def pill(x, y, w, h, label, sub="", filled=False):
    """A terminal: exit codes. Filled black = failure, white = success."""
    fill, color = (INK, PAPER) if filled else (PAPER, INK)
    svg.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{h / 2}" fill="{fill}" stroke="{INK}" stroke-width="3"/>')
    text(x + w / 2, y + (h / 2 + 6 if not sub else h / 2 - 3), label, 18, bold=True, color=color, anchor="middle")
    if sub:
        text(x + w / 2, y + h / 2 + 17, sub, 13, color=color, anchor="middle")


def arrow(points, label="", dashed=False, label_at=0.5, label_dy=-8, head=True, label_seg=None):
    """Orthogonal arrow through the given points; optional label on the longest segment."""
    dash = ' stroke-dasharray="7 5"' if dashed else ""
    d = "M" + " L".join(f"{x},{y}" for x, y in points)
    svg.append(f'<path d="{d}" fill="none" stroke="{INK}" stroke-width="2"{dash}/>')
    if head:
        (x0, y0), (x1, y1) = points[-2], points[-1]
        if x0 == x1:
            s = 1 if y1 > y0 else -1
            tri = f"{x1},{y1} {x1 - 7},{y1 - 13 * s} {x1 + 7},{y1 - 13 * s}"
        else:
            s = 1 if x1 > x0 else -1
            tri = f"{x1},{y1} {x1 - 13 * s},{y1 - 7} {x1 - 13 * s},{y1 + 7}"
        svg.append(f'<polygon points="{tri}" fill="{INK}"/>')
    if label:
        segs = list(zip(points, points[1:]))
        if label_seg is not None:
            (ax, ay), (bx, by) = segs[label_seg]
        else:
            (ax, ay), (bx, by) = max(segs, key=lambda s: abs(s[0][0] - s[1][0]) + abs(s[0][1] - s[1][1]))
        lx, ly = ax + (bx - ax) * label_at, ay + (by - ay) * label_at
        tw = text_width(label, 13, True)
        if ax == bx:  # vertical segment: label to the right of the line
            svg.append(f'<rect x="{lx + 8}" y="{ly - 13}" width="{tw + 12}" height="20" fill="{PAPER}"/>')
            text(lx + 14, ly + 2, label, 13, bold=True)
        else:
            svg.append(f'<rect x="{lx - tw / 2 - 6}" y="{ly + label_dy - 14}" width="{tw + 12}" height="20" fill="{PAPER}"/>')
            text(lx, ly + label_dy, label, 13, bold=True, anchor="middle")


def section(n, y0, y1, title, icons=()):
    """A numbered band: dashed frame with a black tab label."""
    svg.append(
        f'<rect x="30" y="{y0}" width="{BAND_RIGHT - 30}" height="{y1 - y0}" rx="16" fill="none" stroke="{INK}" '
        f'stroke-width="1.5" stroke-dasharray="3 6"/>'
    )
    label = f"{title}"
    tw = text_width(label, 16, True) + 40 + 26 * len(icons) + 10
    svg.append(f'<rect x="50" y="{y0 - 18}" width="{tw + 36}" height="36" rx="18" fill="{INK}"/>')
    svg.append(f'<circle cx="68" cy="{y0}" r="12" fill="{PAPER}"/>')
    text(68, y0 + 5, str(n), 15, bold=True, anchor="middle")
    tx = 90
    for name in icons:
        icon(name, tx, y0 - 11, 22, PAPER)
        tx += 28
    text(tx + 2, y0 + 6, label, 16, bold=True, color=PAPER)


# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------
text(40, 58, "RegressionGate: end-to-end flow", 30, bold=True)
text(40, 88, "What happens from a prompt change to a merge decision. Every pull request runs this.", 16, color=SOFT)
# legend
lx = 1210
svg.append(f'<path d="M{lx},52 H{lx + 50}" stroke="{INK}" stroke-width="2"/>')
text(lx + 60, 57, "flow", 14)
svg.append(f'<path d="M{lx + 120},52 H{lx + 170}" stroke="{INK}" stroke-width="2" stroke-dasharray="7 5"/>')
text(lx + 180, 57, "data written / note", 14)
svg.append(f'<rect x="{lx}" y="70" width="34" height="20" rx="10" fill="{INK}"/>')
text(lx + 44, 85, "fail exit", 14)
svg.append(f'<rect x="{lx + 130}" y="70" width="34" height="20" rx="10" fill="{PAPER}" stroke="{INK}" stroke-width="2.5"/>')
text(lx + 174, 85, "pass exit", 14)

# ---------------------------------------------------------------------------
# 1. Developer and GitHub
# ---------------------------------------------------------------------------
section(1, 130, 330, "DEVELOPER & GITHUB", icons=("git", "github"))
box(80, 170, 440, 120, "Change the agent", [
    "edit the prompt, swap the model,",
    "or edit the dataset, on a branch",
], icons=("git",))
box(680, 170, 440, 120, "Open / update a pull request", [
    "git push → PR into main",
    "every push re-runs the check",
], icons=("github",))
box(1280, 170, 440, 120, "Workflow eval.yml starts", [
    "on: pull_request (to main)",
    "a newer push cancels the old run",
], icons=("githubactions",))
arrow([(520, 230), (680, 230)], "commit + push")
arrow([(1120, 230), (1280, 230)], "triggers")

# ---------------------------------------------------------------------------
# 2. CI job
# ---------------------------------------------------------------------------
section(2, 370, 640, "CI JOB · GITHUB ACTIONS RUNNER", icons=("githubactions",))
ci = [
    ("Checkout", ["full git history", "(origin/main available)"], ("github",)),
    ("Set up uv", ["pinned to a commit SHA", "Python 3.12"], ("uv", "python")),
    ("Install", ["uv sync --locked", "--no-build: wheels only"], ("uv",)),
    ("Unit tests", ["62 offline tests", "fake agent + fake judge"], ("pytest",)),
    ("rgate validate", ["schema + sha256 hash", "bumped vs origin/main?"], ("pydantic",)),
    ("API key", ["ANTHROPIC_API_KEY", "repo secret is set?"], ("anthropic",)),
]
xs = [60 + i * 280 for i in range(6)]
for x, (title, lines, ics) in zip(xs, ci):
    box(x, 420, 255, 130, title, lines, icons=ics)
for a, b in zip(xs, xs[1:]):
    arrow([(a + 255, 485), (b, 485)])
text(W / 2, 600, "any of these steps fails  →  the job fails  →  red check, merge blocked", 14, bold=True, anchor="middle")
arrow([(1500, 290), (1500, 404), (187, 404), (187, 420)])

# ---------------------------------------------------------------------------
# 3. rgate run
# ---------------------------------------------------------------------------
section(3, 680, 1730, "rgate run --repeats 3 --require-baseline", icons=("python",))
arrow([(1587, 550), (1587, 655), (550, 655), (550, 730)])
box(60, 730, 520, 130, "Load the dataset", [
    "datasets/support: 25 cases (JSONL)",
    "+ manifest.json (version, sha256)",
    "every row checked by Pydantic",
], icons=("pydantic", "json"))
box(640, 730, 520, 130, "Fan out: 25 cases × 3 repeats", [
    "= 75 attempts, 5 parallel workers",
    "every span tagged with the run_id",
    "a crash fails one attempt, not the run",
], icons=("python",))
cylinder(1240, 715, 480, 160, "traces.db", [
    "SQLite (WAL), one row per span:",
    "eval → agent → llm / tool → judge",
    "tokens · cost · latency · error",
], icons=("sqlite",))
arrow([(580, 795), (640, 795)])

# one attempt
svg.append(
    f'<rect x="60" y="905" width="1660" height="640" rx="14" fill="none" stroke="{INK}" stroke-width="2" '
    f'stroke-dasharray="10 6"/>'
)
text(80, 935, "ONE ATTEMPT  =  one eval.case span  (repeated 75×)", 15, bold=True)
arrow([(900, 860), (900, 905)])
arrow([(1480, 905), (1480, 875)], "@trace: every step is saved", dashed=True, label_at=0.5)

box(100, 960, 360, 120, "Agent.run(ticket)", [
    "SupportAgent, plain Python loop",
    "up to 6 turns",
], icons=("python",))
box(560, 960, 380, 120, "Claude Haiku 5.5", [
    "Messages API + 3 tool schemas",
    "answers with text or tool_use",
], icons=("claude", "anthropic"))
box(1040, 960, 380, 120, "Tools (fake store data)", [
    "lookup_order · escalate",
    "check_refund_policy",
], icons=("python",))
arrow([(460, 1020), (560, 1020)], "messages")
arrow([(940, 1005), (1040, 1005)], "tool_use")
arrow([(1040, 1045), (940, 1045)], "tool_result", label_dy=26)

box(560, 1130, 380, 120, "Parse final answer", [
    "→ TicketResponse (Pydantic)",
    "{action, order_id, reply}",
    "bad JSON = failed check, no crash",
], icons=("pydantic", "json"))
arrow([(750, 1080), (750, 1130)], "stop_reason = end_turn")

diamond(750, 1350, 340, 150, "7 hard checks", ["all pass?"])
arrow([(750, 1250), (750, 1275)])
box(100, 1290, 360, 150, "The hard checks (code, free)", [
    "valid_json · action · order_id",
    "must_call · must_not_call",
    "cost ≤ $0.01 · latency ≤ 30 s",
], dashed=True)
arrow([(460, 1350), (580, 1350)], dashed=True, head=False)

box(1040, 1270, 380, 160, "Claude Sonnet 5.5 judge", [
    "rubric v2: F1 invented facts",
    "F2 contradiction · F3 criteria",
    "F4 unsafe · effort: high",
    "→ {reason, score 1-5, passed}",
], icons=("claude", "anthropic"))
cylinder(1480, 1270, 220, 160, "cache", [
    "judge_cache.db",
    "same input",
    "= same verdict",
], icons=("sqlite",))
arrow([(920, 1350), (1040, 1350)], "yes")
arrow([(1420, 1335), (1480, 1335)])
arrow([(1480, 1375), (1420, 1375)])

box(100, 1465, 360, 60, "✗  Attempt fails, judge skipped")
arrow([(750, 1425), (750, 1495), (460, 1495)], "no")
box(1040, 1465, 380, 60, "✓ / ✗  passed AND score ≥ 3")
arrow([(1230, 1430), (1230, 1465)])

box(60, 1580, 820, 120, "Score the run", [
    "pass rate = passed attempts / 75",
    "each case ✓/✗ = majority vote of its 3 repeats",
    "p50 / p95 latency · agent cost · judge cost (separate)",
], icons=("python",))
box(960, 1580, 440, 120, "runs/<run_id>.json", [
    "the full result: every attempt,",
    "checks, verdicts, trace IDs",
], icons=("json",), shape="doc")
arrow([(280, 1525), (280, 1580)])
arrow([(1230, 1525), (1230, 1555), (620, 1555), (620, 1580)])
arrow([(880, 1640), (960, 1640)], "saved", dashed=True)

# ---------------------------------------------------------------------------
# 4. The gate
# ---------------------------------------------------------------------------
section(4, 1770, 2290, "THE GATE · COMPARE TO THE BASELINE")
arrow([(470, 1700), (470, 1745), (800, 1745), (800, 1815)])
box(60, 1830, 440, 130, "baselines/<dataset sha256>.json", [
    "a known-good run, saved on purpose",
    "(--save-baseline), committed in a PR",
    "new dataset hash = needs new baseline",
], icons=("json",), shape="doc")
diamond(800, 1895, 400, 160, "Measured the same way?", [
    "repeats · judge model · rubric",
    "effort · scoring version",
])
arrow([(500, 1895), (600, 1895)])
pill(1250, 1860, 320, 70, "exit 2", "not comparable", filled=True)
arrow([(1000, 1895), (1250, 1895)], "no")

diamond(800, 2120, 400, 160, "Any gate tripped?")
arrow([(800, 1975), (800, 2040)], "yes")
box(60, 2055, 440, 150, "Gates", [
    "pass rate drops > 10 points",
    "hard regression: 3/3 → 0/3",
    "agent cost > $0.50 · p95 > 15 s",
    "no baseline (--require-baseline)",
], dashed=True)
arrow([(500, 2120), (600, 2120)], dashed=True, head=False)
pill(1250, 2085, 320, 70, "exit 1", "regression or budget", filled=True)
arrow([(1000, 2120), (1250, 2120)], "yes")
pill(640, 2225, 320, 50, "exit 0  ·  pass")
arrow([(800, 2200), (800, 2225)], "no")

# ---------------------------------------------------------------------------
# 5. Results on the PR
# ---------------------------------------------------------------------------
section(5, 2340, 2580, "RESULTS ON THE PULL REQUEST", icons=("github",))
arrow([(800, 2275), (800, 2315)], head=False)
arrow([(1570, 1895), (1660, 1895), (1660, 2315)], head=False)
arrow([(1570, 2120), (1660, 2120)], head=False)
arrow([(520, 2315), (1660, 2315)], "exit code + report are always posted", head=False, label_at=0.62)
for cx in (520, 900, 1480):
    arrow([(cx, 2315), (cx, 2385)])
box(60, 2385, 520, 150, "PR comment (report.md)", [
    "verdict + pass-rate table vs baseline",
    "newly failing / newly passing cases",
    "failing cases with trace IDs",
    "one comment, edited on every push",
], icons=("github", "markdown"))
box(640, 2385, 520, 150, "Artifact: eval-traces", [
    "traces.db · runs/*.json",
    "report.md · eval.log",
    "kept for 14 days",
], icons=("githubactions", "sqlite"))
box(1220, 2385, 520, 150, "Required check: eval", [
    "exit 0  →  ✓ green, merge allowed",
    "exit 1 / 2  →  ✗ red, merge blocked",
    "branch protection, no bypass",
], icons=("github",))

# ---------------------------------------------------------------------------
# 6. Debug and fix
# ---------------------------------------------------------------------------
section(6, 2630, 2830, "DEBUG & FIX LOOP")
box(60, 2680, 520, 120, "rgate trace <id> --db traces.db", [
    "span tree of the failing attempt",
    "e.g. check_refund_policy never ran",
], icons=("python", "sqlite"))
box(640, 2680, 520, 120, "Fix on the same branch", [
    "restore the rule, bump PROMPT_VERSION",
    "push → CI runs again (back to 1)",
], icons=("git",))
box(1220, 2680, 520, 120, "Merge when green", [
    "baseline stays the same unless",
    "re-saved on purpose, in its own PR",
], icons=("github",))
arrow([(900, 2535), (900, 2600), (420, 2600), (420, 2680)], "download the artifact")
arrow([(580, 2740), (640, 2740)])
arrow([(1480, 2535), (1480, 2680)], "green")
# loop back to the PR box at the top
arrow([(900, 2800), (900, 2855), (1805, 2855), (1805, 112), (900, 112), (900, 170)], "push again: back to 1",
      label_seg=3, label_at=0.25)

# ---------------------------------------------------------------------------
doc = (
    f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">'
    f'<rect width="{W}" height="{H}" fill="{PAPER}"/>' + "".join(svg) + "</svg>"
)
OUT.mkdir(parents=True, exist_ok=True)
(OUT / "flowchart.svg").write_text(doc)
import cairosvg  # noqa: E402  (only needed to render; imported late so layout errors show first)

cairosvg.svg2png(bytestring=doc.encode(), write_to=str(OUT / "flowchart.png"), output_width=W)
print(f"wrote {OUT / 'flowchart.svg'} and {OUT / 'flowchart.png'} ({W}x{H})")
