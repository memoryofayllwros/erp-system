from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer

styles = getSampleStyleSheet()
styleN = styles["Italic"]
styleB = styles["BodyText"]
styleBH = styles["Heading2"]
styleTitle = styles["Title"]

story = []


def add_third_page():
    # Title style: Normal font, size 12
    house_rules_title_style = ParagraphStyle(
        "houseRulesTitle",
        parent=styleN,
        fontSize=12,
        leading=14,
        spaceAfter=6,
    )

    # Body text style: Normal font, size 11
    house_rules_body_style = ParagraphStyle(
        "houseRulesBody",
        parent=styleN,
        fontSize=11,
        leading=14,
        leftIndent=0,
        spaceAfter=4,
    )

    # Title paragraph (not bold)
    house_rules_title = "House Rules for Contractor/Worker Working at WCHH"
    story.append(Paragraph(house_rules_title, house_rules_title_style))

    # Body text (plain paragraphs, each rule as separate paragraph for alignment)
    rules = [
        "i. Worker is required to register in and out daily in person at the Facilities Management Office (FMO) when carrying out works at hospital areas.",
        "ii. Contractor/worker shall carry out the works in accordance with the period and time specified in the works permit.",
        "iii. Site works outside normal office hours is not allowed unless prior approval from Facilities Management Department (FMD) of revised works permit specifying the new working hours is obtained by contractor. Contractor/worker shall inform staff of the Department concerned regarding the daily schedule of works outside office hours. Upon completion of day works, the contractor shall inform and wait FMO staff to come and lock the doors before leaving the works site.",
        "iv. Worker must wear the temporary works permit badge issued by FMO when working in hospital.",
        "v. Worker is required to contact FMO in person for arrangement of access to locked rooms/areas. Upon completion of day works, the contractor shall inform and wait FMO staff to come and lock the doors before leaving the works site. Worker is also required to contact concerned end-users for granting access and necessary arrangement inside their premises.",
        "vi. All works shall be carried out by licensed /competent workers of respective trades according to relevant regulations, ordinances and codes of practice in force.",
        "vii. Contractor shall provide appropriate site safety measures to ensure the safety of workers, patients, hospital staffs and the general public.",
        "viii. Precautionary measures shall be taken to prevent damages to hospital facilities.",
        "ix. Contractor shall obtain prior approval from FMD before any suspension of building services installations/system is proceeded.",
        "x. For works requiring suspension of fire services installations, prior notification to FSD and FMO is required in accordance with Fire Services Department requirements. Appropriate fire safety equipment should be provided at site to meet the specific needs of each project.",
        "xi. Construction waste and debris shall be sent to hospital dumping sites designated by FMD through hospital lifts (Lift no. 1,2, 13 and 14) within specified time periods (9:30am to 11:30am and 2:30pm to 3:30pm) for temporary storage before final disposal to government landfill.",
        "xii. Contractor shall obtain prior agreement with FMO in relation to delivery and transportation of material and equipment to hospital in bulk quantities.",
        "xiii. No facilities of the hospital can be used without prior approval from FMD.",
        "xiv. Contractor/worker shall keep the works site tidy.",
        "xv. Worker shall observe the Hospital Authority Regulation prohibiting smoking, use of offensive language, indecent behaviour and causing annoyance to the patients in hospital areas.",
        "xvi. Contractor/workers shall comply with all current ordinance, regulations, codes of practice of HKSAR and other requirements stipulated by Hospital Authority/ WCCH.",
    ]

    for rule in rules:
        story.append(Paragraph(rule, house_rules_body_style))

    story.append(PageBreak())
