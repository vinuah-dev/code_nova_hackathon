"""Generates the fictional Voltaro Mobility demo assets (logos, poster, brand-book PDF).

Everything here is synthetic so the demo needs no third-party images.
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

INDIGO, AMBER, MIDNIGHT, CLOUD = "#3B2FC9", "#FFB020", "#0E1A3A", "#F5F6FA"


def _font(size: int, bold: bool = True):
    for name in (("arialbd.ttf", "segoeuib.ttf") if bold else ("arial.ttf", "segoeui.ttf")):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default(size=size)


def official_logo(path: Path) -> None:
    img = Image.new("RGB", (640, 200), "white")
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((20, 20, 180, 180), radius=36, fill=INDIGO)
    d.polygon([(55, 60), (85, 60), (100, 120), (115, 60), (145, 60), (115, 145), (85, 145)], fill="white")
    d.ellipse((130, 40, 152, 62), fill=AMBER)
    d.text((205, 48), "voltaro", font=_font(100), fill=MIDNIGHT)
    img.save(path)


def misused_logo(path: Path, official: Path) -> None:
    """The official mark, horizontally stretched and recoloured — a classic misuse."""
    img = Image.open(official).convert("RGB")
    px = img.load()
    for x in range(img.width):
        for y in range(img.height):
            r, g, b = px[x, y]
            if (r, g, b) != (255, 255, 255) and b > r and b > 150:  # indigo -> off-brand pink-red
                px[x, y] = (226, 67, 98)
    img = img.resize((int(img.width * 1.45), img.height))
    img.save(path)


def poster(path: Path, logo_used: Path) -> None:
    img = Image.new("RGB", (1080, 1350), "#D9412F")  # off-brand red background
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((70, 380, 1010, 1000), radius=40, fill="#F07C5A")  # low-contrast panel
    d.text((90, 120), "DIWALI DHAMAKA", font=_font(96), fill="#FFE27A")
    d.text((120, 430), "India's fastest", font=_font(78), fill="#FFF3EC")
    d.text((120, 530), "electric scooter", font=_font(78), fill="#FFF3EC")
    d.text((120, 680), "150 km range. Guaranteed.", font=_font(52, False), fill="#FFF3EC")
    d.text((120, 760), "Zero maintenance!!", font=_font(52, False), fill="#FFF3EC")
    d.rounded_rectangle((120, 860, 560, 950), radius=45, fill="#FFE27A")
    d.text((165, 878), "BOOK NOW", font=_font(46), fill="#D9412F")
    lg = Image.open(logo_used).convert("RGB")
    lg.thumbnail((620, 140))
    img.paste(lg, (230, 1120))
    img.save(path)


def _pdf_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def brand_book_pdf(path: Path, pages: list[list[str]]) -> None:
    """Minimal text PDF writer (Helvetica) so the demo has a real PDF to upload."""
    objs: list[bytes] = []
    font_id = 3 + 2 * len(pages)
    kids = []
    for i, lines in enumerate(pages):
        page_id, content_id = 3 + 2 * i, 4 + 2 * i
        kids.append(f"{page_id} 0 R")
        ops = ["BT", "/F1 11 Tf", "14 TL", "56 790 Td"]
        for ln in lines:
            if ln.startswith("# "):
                ops += ["/F1 16 Tf", f"({_pdf_escape(ln[2:])}) Tj", "T*", "/F1 11 Tf"]
            else:
                ops += [f"({_pdf_escape(ln)}) Tj", "T*"]
        ops.append("ET")
        stream = "\n".join(ops).encode("latin-1", "replace")
        objs.append((page_id, f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 {font_id} 0 R >> >> /Contents {content_id} 0 R >>".encode()))
        objs.append((content_id, b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream"))
    objs.insert(0, (2, f"<< /Type /Pages /Kids [{' '.join(kids)}] /Count {len(pages)} >>".encode()))
    objs.insert(0, (1, b"<< /Type /Catalog /Pages 2 0 R >>"))
    objs.append((font_id, b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"))
    objs.sort()
    out = bytearray(b"%PDF-1.4\n")
    offsets = {}
    for oid, body in objs:
        offsets[oid] = len(out)
        out += f"{oid} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    for oid, _ in objs:
        out += f"{offsets[oid]:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    path.write_bytes(bytes(out))


BRAND_BOOK = [
    ["# Voltaro Brand Book 2026 (fictional demo organisation)",
     "",
     "# 1. Who we are",
     "Voltaro Mobility makes electric scooters for everyday city riders in India.",
     "Our promise is calm, dependable urban mobility. We sell confidence, not adrenaline.",
     "",
     "# 2. Festive and seasonal campaigns",
     "Festive campaigns should greet riders warmly and focus on family, travel and togetherness.",
     "Never use firecracker imagery or noise-related themes; our brand stands for cleaner, quieter cities.",
     "Festive offers must state the exact validity dates and link to the full terms and conditions.",
     "",
     "# 3. Competitors",
     "Never name or mock competitors, and never compare with petrol scooters using insulting language.",
     "Comparative claims are allowed only when they appear in the Approved Claims register.",
     ],
    ["# 4. Visual identity summary",
     "Primary colour Voltaro Indigo #3B2FC9. Accent Spark Amber #FFB020, used sparingly for calls to action.",
     "Text colour Midnight #0E1A3A on Cloud #F5F6FA or white. Red is reserved for safety warnings only.",
     "The logo must never be stretched, recoloured, rotated or placed on busy backgrounds.",
     "",
     "# 5. Inclusive communication",
     "Write for riders of every age and ability. Every image needs meaningful alt text.",
     "Keep sentences short. Use CamelCase in hashtags so screen readers can pronounce them.",
     ],
]

# A dealer brochure with deliberate mistakes, for the "Document" sample in Content Studio.
DEALER_BROCHURE = [
    ["# Voltaro Glide-S1 - Dealer Brochure (fictional demo, draft from an agency)",
     "",
     "# Why riders love it",
     "The Glide-S1 is the fastest electric scooter in India and the cheapest way to beat traffic.",
     "Ride up to 110 km on a single charge and reach a top speed of 80 km/h.",
     "Every scooter comes with a 5 years battery warranty, guaranteed.",
     "",
     "# Charging",
     "Charge 0-80% in 60 minutes with the Voltaro Fast Charger at any dealer.",
     "",
     "# Offer",
     "Festive dhamaka offer valid till 31 Oct 2025. Hurry, stocks are limited!!",
     "Click here to find your nearest dealer.",
     ],
]

# A guideline update for the "Extract rules" demo: new product, service, words and colour not yet in the Brand Brain.
GUIDELINE_UPDATE = [
    ["# Voltaro Brand Guidelines - Update 2026.2 (fictional demo organisation)",
     "",
     "# New service: Voltaro Care+",
     "Always write the service name as 'Voltaro Care+' with the plus sign attached.",
     "Voltaro Care+ costs Rs 2,499 per year and includes doorstep servicing.",
     "Voltaro Care+ covers roadside assistance within 25 km of any Voltaro Experience Centre.",
     "",
     "# Words we no longer use",
     "Never use 'insane' or 'mind-blowing' to describe performance; say 'responsive' instead.",
     "Do not use 'lifetime free service'; no service plan is free for life.",
     "",
     "# Approved claim",
     "We may say 'Rated 4.6 out of 5 by Voltaro riders' (evidence: rider survey, September 2026).",
     "",
     "# New accent colour",
     "Ocean Teal #0FA3B1 is approved for charging and sustainability visuals only.",
     ],
]

DIWALI_CAPTION = ("Meet the all-new VoltaroGlide S1 — India's fastest electric scooter!! Get 150 km on a single charge, "
                  "GUARANTEED. Zero maintenance and an unbeatable price make it a total no-brainer. "
                  "Offer valid till 31 Dec 2025. Click here to book your ride! #voltaroglidediwali")


def generate(brand_dir: Path, demo_dir: Path) -> dict:
    """Official logo goes to the (writable) data dir. Sample files for the Content Studio go to
    web/demo, but only if missing: on read-only hosts (e.g. Vercel) the committed copies are used."""
    brand_dir.mkdir(parents=True, exist_ok=True)
    logo = brand_dir / "voltaro_logo_primary.png"
    official_logo(logo)
    needed = ["logo_used_in_poster.png", "diwali_poster.png", "Voltaro_Brand_Book_2026.pdf", "diwali_caption.txt", "voltaro_logo_primary.png",
              "Voltaro_Dealer_Brochure_draft.pdf", "Voltaro_Guidelines_Update_2026.pdf"]
    if all((demo_dir / n).exists() for n in needed):
        return {"logo": logo}
    try:
        demo_dir.mkdir(parents=True, exist_ok=True)
        bad = demo_dir / "logo_used_in_poster.png"
        misused_logo(bad, logo)
        poster(demo_dir / "diwali_poster.png", bad)
        brand_book_pdf(demo_dir / "Voltaro_Brand_Book_2026.pdf", BRAND_BOOK)
        brand_book_pdf(demo_dir / "Voltaro_Dealer_Brochure_draft.pdf", DEALER_BROCHURE)
        brand_book_pdf(demo_dir / "Voltaro_Guidelines_Update_2026.pdf", GUIDELINE_UPDATE)
        (demo_dir / "diwali_caption.txt").write_text(DIWALI_CAPTION, encoding="utf-8")
        import shutil
        shutil.copy(logo, demo_dir / "voltaro_logo_primary.png")
    except OSError:
        pass  # read-only filesystem: sample files are optional
    return {"logo": logo}
