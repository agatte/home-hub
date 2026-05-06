"""
Generate a printable single-page cheat sheet of every voice command the
Custom Alexa Skill recognizes.

Run:  python scripts/generate_voice_command_sheet.py

Outputs alexa_skill/voice_commands.pdf — letter portrait, two-column layout,
one page. Re-run after adding or changing intents in
alexa_skill/interaction_model.json.
"""
from __future__ import annotations

from pathlib import Path

from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

# ---- Content (single source of truth for the cheat sheet) ----

INK = HexColor("#1a1a1a")
ACCENT = HexColor("#7a3f00")  # warm amber, reads like the dashboard
MUTED = HexColor("#6b6b6b")
RULE = HexColor("#cccccc")
WARN = HexColor("#a13b00")

# Each section: (heading, [(label, examples)]).
SECTIONS = [
    ("MODES", [
        ("Set a mode",
         "set relax mode · turn on gaming · make it watching"),
        ("Modes",
         "gaming · working · watching · social · relax · cooking · sleeping"),
        ("Return to autopilot",
         "auto · back to automatic · release the override"),
    ]),
    ("LIGHTS", [
        ("Brightness",
         "make it brighter · make the lights dimmer · brighter · dimmer"),
    ]),
    ("EFFECTS", [
        ("Effects",
         "candle · fire · sparkle · prism · glisten · opal"),
        ("Start one",
         "turn on the candle effect · start the sparkle effect"),
        ("Stop",
         "stop the effect"),
    ]),
    ("SCENES", [
        ("Scenes",
         "party · neon · miami · arcade · aurora · sunset"),
        ("Run one",
         "run the party scene · activate the aurora scene · set the miami scene"),
    ]),
    ("MUSIC", [
        ("Playback",
         "play · pause · play the music · pause the music"),
        ("Skip",
         "skip this song · next track · go back a song · previous track"),
        ("Volume",
         "turn the music up · music down · bump the song up · make the song go down"),
        ("Heads up: volume gotcha",
         "Alexa intercepts \"louder\" / \"quieter\" before the skill runs. "
         "Use \"up\" / \"down\" with \"music\" or \"song\"."),
    ]),
    ("DO NOT DISTURB", [
        ("Enable (2 hour window)",
         "enable do not disturb · turn on do not disturb"),
        ("Disable",
         "turn off do not disturb · cancel do not disturb"),
    ]),
    ("STATUS", [
        ("Current mode",
         "what mode am I in · what's the mode · current mode"),
        ("Now playing",
         "what's playing · what song is this · what am I listening to"),
    ]),
]

# Wake-word framing — Alexa requires either "tell" or "ask" with the
# invocation name to route the utterance to the custom skill.
INVOCATION = "command center"
WAKE_PATTERNS = [
    f'Alexa, tell {INVOCATION} to [command]',
    f'Alexa, ask {INVOCATION} [command]',
    f'Alexa, open {INVOCATION}   (then say [command])',
]

PREREQ = (
    "Alexa+ (Amazon's generative-AI tier) must be DISABLED on your Echo or "
    "custom skills won't route reliably. App → More → Settings → Alexa+."
)


def build_pdf(output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=LETTER,
        topMargin=0.5 * inch,
        bottomMargin=0.5 * inch,
        leftMargin=0.55 * inch,
        rightMargin=0.55 * inch,
        title="Home Hub Voice Commands",
        author="Home Hub",
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "title", parent=styles["Title"],
        fontName="Helvetica-Bold", fontSize=22, leading=26,
        textColor=INK, spaceAfter=4,
    )
    subtitle_style = ParagraphStyle(
        "subtitle", parent=styles["Normal"],
        fontName="Helvetica", fontSize=9.5, leading=13,
        textColor=MUTED, spaceAfter=10,
    )
    section_style = ParagraphStyle(
        "section", parent=styles["Heading2"],
        fontName="Helvetica-Bold", fontSize=11, leading=14,
        textColor=ACCENT, spaceBefore=4, spaceAfter=3,
        letterSpacing=1,
    )
    label_style = ParagraphStyle(
        "label", parent=styles["Normal"],
        fontName="Helvetica-Bold", fontSize=8.5, leading=11,
        textColor=INK, spaceAfter=0,
    )
    example_style = ParagraphStyle(
        "example", parent=styles["Normal"],
        fontName="Helvetica", fontSize=8.5, leading=11,
        textColor=INK, spaceAfter=4, leftIndent=8,
    )
    warn_label_style = ParagraphStyle(
        "warn_label", parent=label_style, textColor=WARN,
    )
    warn_style = ParagraphStyle(
        "warn", parent=example_style,
        textColor=WARN, fontName="Helvetica-Oblique",
    )
    footer_style = ParagraphStyle(
        "footer", parent=styles["Normal"],
        fontName="Helvetica-Oblique", fontSize=8, leading=10,
        textColor=MUTED, spaceBefore=6,
    )

    story: list = []

    # Header
    story.append(Paragraph("Home Hub voice commands", title_style))
    wake_text = " &nbsp;·&nbsp; ".join(
        f'<font face="Courier">{p}</font>' for p in WAKE_PATTERNS
    )
    story.append(Paragraph(wake_text, subtitle_style))

    # Build the section blocks first so we can balance two columns.
    def render_section(heading: str, rows: list[tuple[str, str]]) -> list:
        block: list = [Paragraph(heading, section_style)]
        for label, examples in rows:
            is_warn = label.lower().startswith("heads up")
            l_style = warn_label_style if is_warn else label_style
            e_style = warn_style if is_warn else example_style
            block.append(Paragraph(label, l_style))
            block.append(Paragraph(examples, e_style))
        return block

    blocks = [render_section(h, rows) for h, rows in SECTIONS]

    # Two-column layout: split sections roughly in half by row count so
    # both columns end at similar heights. Doesn't need to be perfect —
    # reportlab handles the overflow gracefully.
    counts = [sum(len(rows) for _, rows in [SECTIONS[i]]) for i in range(len(SECTIONS))]
    total = sum(counts)
    running = 0
    split = len(SECTIONS)
    for i, c in enumerate(counts):
        running += c
        if running >= total / 2:
            split = i + 1
            break

    left_col = []
    for b in blocks[:split]:
        left_col.extend(b)
    right_col = []
    for b in blocks[split:]:
        right_col.extend(b)

    column_table = Table(
        [[left_col, right_col]],
        colWidths=[3.6 * inch, 3.6 * inch],
    )
    column_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    story.append(column_table)

    story.append(Spacer(1, 8))
    story.append(Paragraph(
        f"<b>Prerequisite:</b> {PREREQ}",
        footer_style,
    ))
    story.append(Paragraph(
        "Built from <font face=\"Courier\">alexa_skill/interaction_model.json</font>. "
        "Re-run scripts/generate_voice_command_sheet.py after adding intents.",
        footer_style,
    ))

    doc.build(story)


if __name__ == "__main__":
    repo_root = Path(__file__).resolve().parent.parent
    out = repo_root / "alexa_skill" / "voice_commands.pdf"
    build_pdf(out)
    print(f"Wrote {out}")
