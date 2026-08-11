"""Generate the sample knowledge-base PDF used to demo the retrieval tool.

    uv run --with fpdf2 python scripts/make_sample_pdf.py

The output is committed, so you only need to run this if you change the content.
The document is illustrative demo data, not an official policy document — the
disclaimer is part of the generated PDF on purpose, so it survives ingestion and
shows up in retrieved chunks.
"""

from pathlib import Path

from fpdf import FPDF

OUT = Path("knowledge/spinny-policies.pdf")

DISCLAIMER = """\
SAMPLE DATA FOR A TECHNICAL DEMO. This document was written to exercise a \
retrieval-augmented voice agent. It is not an official Spinny document and must \
not be relied on for actual terms. Figures are illustrative."""

SECTIONS: list[tuple[str, str]] = [
    (
        "5-Day Money-Back Guarantee",
        """\
A customer may return a purchased car within 5 days of delivery, or 300 km of \
driving, whichever comes first. The full purchase amount is refunded to the \
original payment method within 7 to 10 working days. The car must be returned in \
the same condition, with no new damage and no modifications. Fuel costs and any \
traffic fines incurred during the period are not refunded.""",
    ),
    (
        "200-Point Inspection",
        """\
Every car listed is inspected against 200 checkpoints covering engine, \
transmission, suspension, brakes, electricals, air conditioning, interiors and \
exteriors. Cars that fail any safety-critical checkpoint are rejected and never \
listed. The full inspection report is available to the customer before purchase \
and is shared as a PDF on request.""",
    ),
    (
        "One-Year Warranty",
        """\
Assured cars include a 1-year comprehensive warranty covering the engine, \
transmission and up to 1,000 mechanical and electrical parts. The warranty starts \
on the delivery date and is valid at any authorised service centre. Consumables \
such as oil, filters, tyres, brake pads and clutch plates are not covered. \
Warranty extension of up to 2 additional years may be purchased at the time of \
sale.""",
    ),
    (
        "Free RC Transfer",
        """\
Registration certificate transfer to the buyer's name is handled at no extra cost \
and is completed within 45 to 60 days of delivery. The customer is kept informed \
at each stage. If the transfer is delayed beyond 90 days for reasons attributable \
to Spinny, the customer is eligible for compensation of INR 5,000.""",
    ),
    (
        "Fixed Price, No Negotiation",
        """\
The listed price is the final price. There is no haggling and no hidden charges. \
The price shown includes the inspection, the warranty and the RC transfer. \
Insurance, road tax where applicable, and optional add-ons such as extended \
warranty are quoted separately and clearly before payment.""",
    ),
    (
        "Test Drive at Home",
        """\
A free test drive can be booked at the customer's home or office at a chosen time \
slot. There is no obligation to buy. Test drives are available in cities where \
Spinny operates, and slots may be rescheduled up to 2 hours before the booked \
time at no cost.""",
    ),
    (
        "Buyback Promise",
        """\
A car bought from Spinny can be sold back within 1 year of purchase at a \
guaranteed minimum of 80 percent of the original purchase price, provided the car \
has been driven under 15,000 km in that year, has no accident history in that \
period, and has a valid service record.""",
    ),
    (
        "Financing and Documents",
        """\
Loans are available through partner banks with approval typically within 48 \
hours. The documents required are a PAN card, Aadhaar card, 3 months of bank \
statements and 3 months of salary slips for salaried applicants, or 2 years of \
income tax returns for self-employed applicants. Down payment starts at 10 \
percent of the car value.""",
    ),
    (
        "Delivery Timelines",
        """\
Once payment is complete, home delivery takes 3 to 7 working days depending on \
the city and on documentation. The customer receives the car with a full tank of \
fuel, both sets of keys where available, the service history and the inspection \
report.""",
    ),
    (
        "Support Hours",
        """\
Customer support is available every day from 9 AM to 9 PM IST. Post-sale service \
requests are acknowledged within 24 hours and a resolution timeline is shared \
within 48 hours.""",
    ),
]


def build() -> None:
    pdf = FPDF(format="A4", unit="mm")
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.set_margins(20, 18, 20)
    pdf.add_page()

    pdf.set_font("Helvetica", "B", 18)
    pdf.multi_cell(0, 9, "Spinny - Customer Policies (Sample)")
    pdf.ln(2)

    pdf.set_font("Helvetica", "I", 8.5)
    pdf.set_text_color(120, 120, 120)
    pdf.multi_cell(0, 4.2, DISCLAIMER)
    pdf.set_text_color(0, 0, 0)
    pdf.ln(4)

    for title, body in SECTIONS:
        pdf.set_font("Helvetica", "B", 12)
        pdf.multi_cell(0, 6, title)
        pdf.ln(0.5)
        pdf.set_font("Helvetica", "", 10.5)
        pdf.multi_cell(0, 5, body)
        pdf.ln(3.5)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(OUT))
    print(f"wrote {OUT} ({OUT.stat().st_size:,} bytes, {len(SECTIONS)} sections)")


if __name__ == "__main__":
    build()
