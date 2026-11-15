"""Draw a high-level system overview using Pillow, without loading datasets.

Run: python scripts/generate_system_diagram.py
"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "docs" / "sistema-general.png"
SCALE = 2
WIDTH, HEIGHT = 2000, 1280
INK, LINE = "#243247", "#677488"
image = Image.new("RGB", (WIDTH * SCALE, HEIGHT * SCALE), "white")
draw = ImageDraw.Draw(image)


def font(size, bold=False):
    filename = "arialbd.ttf" if bold else "arial.ttf"
    return ImageFont.truetype(str(Path("C:/Windows/Fonts") / filename), size * SCALE)


def text(x, y, value, size=25, bold=False, fill=INK):
    draw.text((x * SCALE, y * SCALE), value, font=font(size, bold),
              fill=fill, anchor="mm")


def box(bounds, number, title, lines, fill, status=None):
    left, top, right, bottom = bounds
    draw.rounded_rectangle(tuple(v * SCALE for v in bounds), radius=14 * SCALE,
                           fill=fill, outline=LINE, width=2 * SCALE)
    center = (left + right) / 2
    text(center, top + 40, f"{number}. {title}", 31, bold=True)
    for index, line in enumerate(lines):
        text(center, top + 95 + index * 39, line)
    if status:
        text(center, bottom - 34, status, 23, bold=True, fill="#8a591b")


def arrow(points, label, label_at):
    draw.line([(x * SCALE, y * SCALE) for x, y in points], fill=LINE,
              width=3 * SCALE, joint="curve")
    x, y = points[-1]
    px, py = points[-2]
    length = ((x - px) ** 2 + (y - py) ** 2) ** 0.5
    ux, uy = (x - px) / length, (y - py) / length
    tip = [(x, y), (x - ux * 15 - uy * 7, y - uy * 15 + ux * 7),
           (x - ux * 15 + uy * 7, y - uy * 15 - ux * 7)]
    draw.polygon([(a * SCALE, b * SCALE) for a, b in tip], fill=LINE)
    xy = tuple(v * SCALE for v in label_at)
    bounds = draw.textbbox(xy, label, font=font(22), anchor="mm")
    draw.rectangle((bounds[0] - 8 * SCALE, bounds[1] - 5 * SCALE,
                    bounds[2] + 8 * SCALE, bounds[3] + 5 * SCALE), fill="white")
    text(*label_at, label, 22)


text(1000, 65, "Flame in Freefall · System overview", 43, bold=True)
text(1000, 120, "From combustion research to evidence exploration", 28)
text(1000, 185, "DATA PREPARATION", 22, bold=True, fill=LINE)

box((80, 240, 600, 550), 1, "NASA PSI sources", [
    "Investigation metadata",
    "Remote file catalog",
    "Documents and experimental tables",
    "Large files remain with NASA",
], "#f4f5f7")
box((740, 240, 1260, 550), 2, "Collection", [
    "Python download scripts",
    "Selected documents and tables",
    "Local copies and download budgets",
    "Source identity and provenance",
], "#eaf2fb")
box((1400, 240, 1920, 550), 3, "Preparation and review", [
    "Text and evidence extraction",
    "Research-card preparation",
    "Table normalization",
    "Validation and scientific review",
], "#eaf2fb")

arrow([(600, 395), (740, 395)], "download", (670, 365))
arrow([(1260, 395), (1400, 395)], "sources", (1330, 365))
arrow([(1660, 550), (1660, 740)], "local artifacts", (1660, 645))

text(770, 655, "APPLICATION QUERIES", 22, bold=True, fill=LINE)
box((1400, 740, 1920, 1080), 4, "Local storage", [
    "SQLite: cards, evidence and catalog",
    "JSON: normalized tables",
    "Turtle: RDF graph export",
    "Review states and traceability",
], "#eaf6f3")
box((740, 740, 1260, 1080), 5, "Backend and API", [
    "Flask · JSON responses",
    "Text search with SQLite FTS5",
    "In-memory RDF: rdflib / SPARQL",
    "Condition filters and coverage",
    "Model: SOSA/SSN · QUDT · PROV",
], "#eaf6f3")
box((80, 740, 600, 1080), 6, "Research interface", [
    "Investigation search",
    "Comparison and evidence views",
    "Condition and file exploration",
    "For researchers and students",
], "#fff5e6", status="Planned · Integration pending")

arrow([(1400, 910), (1260, 910)], "read", (1330, 880))
arrow([(740, 910), (600, 910)], "HTTP / JSON", (670, 880))

text(1000, 1150, "The backend queries SQLite and loads the RDF graph from JSON tables at startup.", 25)
text(1000, 1193, "Cards are prepared before use; the application displays prepared content.", 25)
text(1000, 1242, "Sources: README.md · docs/BACKEND.md · app.py · pipeline/ · backend/", 21, fill=LINE)

OUTPUT.parent.mkdir(parents=True, exist_ok=True)
image.save(OUTPUT)
print(OUTPUT)
