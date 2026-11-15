"""Draw the RDF model in backend/graph.py without loading dataset instances.

Run with a Python installation that already provides Pillow:
    python scripts/generate_ontology_map.py
"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "docs" / "mapa-conocimiento-ontologia-simple.png"
SCALE = 2
WIDTH, HEIGHT = 1900, 1260
INK = "#243247"
LINE = "#677488"
BLUE = "#eaf2fb"
TEAL = "#eaf6f3"
GRAY = "#f4f5f7"
FONT_DIR = Path("C:/Windows/Fonts")


def font(size, bold=False):
    name = "arialbd.ttf" if bold else "arial.ttf"
    return ImageFont.truetype(str(FONT_DIR / name), size * SCALE)


image = Image.new("RGB", (WIDTH * SCALE, HEIGHT * SCALE), "white")
draw = ImageDraw.Draw(image)


def text(position, value, size=24, bold=False, fill=INK, anchor="mm"):
    draw.text(
        tuple(int(v * SCALE) for v in position), value,
        font=font(size, bold), fill=fill, anchor=anchor,
    )


def box(bounds, title, lines, fill=BLUE):
    draw.rounded_rectangle(
        tuple(int(v * SCALE) for v in bounds), radius=12 * SCALE,
        fill=fill, outline=LINE, width=2 * SCALE,
    )
    left, top, right, bottom = bounds
    center = (left + right) / 2
    text((center, top + 32), title, 28, bold=True)
    first_y = top + 75
    for index, line in enumerate(lines):
        text((center, first_y + index * 30), line, 23)


def arrow(points, label, label_at, dashed=False):
    scaled = [(int(x * SCALE), int(y * SCALE)) for x, y in points]
    for (x1, y1), (x2, y2) in zip(scaled, scaled[1:]):
        if dashed:
            length = max(abs(x2 - x1), abs(y2 - y1))
            for start in range(0, length, 18 * SCALE):
                stop = min(start + 10 * SCALE, length)
                draw.line(
                    ((x1 + (x2 - x1) * start / length,
                      y1 + (y2 - y1) * start / length),
                     (x1 + (x2 - x1) * stop / length,
                      y1 + (y2 - y1) * stop / length)),
                    fill=LINE, width=2 * SCALE,
                )
        else:
            draw.line(((x1, y1), (x2, y2)), fill=LINE, width=2 * SCALE)
    x, y = points[-1]
    previous_x, previous_y = points[-2]
    dx, dy = x - previous_x, y - previous_y
    length = (dx * dx + dy * dy) ** 0.5
    ux, uy = dx / length, dy / length
    triangle = [(x, y), (x - ux * 14 - uy * 6, y - uy * 14 + ux * 6),
                (x - ux * 14 + uy * 6, y - uy * 14 - ux * 6)]
    draw.polygon([(int(a * SCALE), int(b * SCALE)) for a, b in triangle], fill=LINE)
    label_xy = tuple(int(v * SCALE) for v in label_at)
    bounds = draw.textbbox(label_xy, label, font=font(23), anchor="mm")
    padding = 4 * SCALE
    draw.rectangle((bounds[0] - padding, bounds[1] - padding,
                    bounds[2] + padding, bounds[3] + padding), fill="white")
    text(label_at, label, 23)


text((950, 60), "Ontology model · Flame in Freefall", 42, bold=True)
text((950, 112), "Resource types and RDF relationships", 26)

# Resource roles are model-level labels, not additional RDF classes.
box((100, 200, 450, 310), "Investigation", ["Membership resource"])
box((100, 430, 450, 540), "Source table", ["prov:Entity"])
box((680, 430, 1060, 540), "Source row", ["prov:Entity"])
box((1350, 430, 1800, 540), "Observation", ["sosa:Observation"], TEAL)
box((1350, 200, 1800, 310), "Observed property", ["sosa:ObservableProperty"], TEAL)
box((100, 710, 530, 850), "Condition", ["ssn:Property · prov:Entity",
    "Numeric: qudt:QuantityValue"], TEAL)
box((680, 710, 1110, 850), "Material / fuel class", ["skos:Concept"], TEAL)
box((1330, 710, 1820, 850), "Result", ["prov:Entity",
    "qudt:QuantityValue or sosa:Result"], TEAL)
box((680, 1010, 1110, 1120), "Extraction activity", ["prov:Activity"], GRAY)

arrow([(770, 430), (770, 255), (450, 255)], "dct:isPartOf", (610, 228))
arrow([(680, 485), (450, 485)], "prov:wasDerivedFrom", (565, 458))
arrow([(1350, 485), (1060, 485)], "sosa:hasFeatureOfInterest", (1205, 452))
arrow([(1575, 430), (1575, 310)], "sosa:observedProperty", (1575, 370))
arrow([(1575, 540), (1575, 710)], "sosa:hasResult", (1575, 625))
arrow([(720, 540), (720, 630), (315, 630), (315, 710)],
      "ssn:hasProperty", (510, 602))
arrow([(895, 540), (895, 710)], "dct:subject", (995, 625))
arrow([(315, 850), (315, 1065), (680, 1065)],
      "prov:wasGeneratedBy", (495, 1035), dashed=True)
arrow([(1575, 850), (1575, 1065), (1110, 1065)],
      "prov:wasGeneratedBy", (1350, 1035), dashed=True)

text((950, 922), "Conditions and results: prov:wasDerivedFrom → source row", 25)
text((950, 962), "Quantities: qudt:unit · qudt:numericValue · minimum/maximum bounds", 24)
text((950, 1174), "Headings identify resource roles; the lines below show RDF types.", 22)
text((950, 1215), "Sources: backend/graph.py · docs/contracts/RDF.md | Model only; no dataset instances", 21)

OUTPUT.parent.mkdir(parents=True, exist_ok=True)
image.save(OUTPUT)
print(OUTPUT)
