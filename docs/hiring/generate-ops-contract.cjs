const fs = require("fs");
const { Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
        Header, Footer, AlignmentType, LevelFormat, HeadingLevel,
        BorderStyle, WidthType, ShadingType, VerticalAlign, PageNumber } = require("docx");

const FONT = "Arial";
const SAGE = "759B8F";
const DARK = "5A7D73";
const tableBorder = { style: BorderStyle.SINGLE, size: 1, color: "CCCCCC" };
const cellBorders = { top: tableBorder, bottom: tableBorder, left: tableBorder, right: tableBorder };

function text(t, opts = {}) {
  return new TextRun({ text: t, font: FONT, size: opts.size || 22, ...opts });
}
function para(children, opts = {}) {
  return new Paragraph({ children: Array.isArray(children) ? children : [children], ...opts });
}
function heading(t) {
  return new Paragraph({ heading: HeadingLevel.HEADING_1, children: [text(t, { bold: true, size: 28, color: DARK })] });
}
function subNum(num, t) {
  return para([text(`${num} `, { bold: true }), text(t)], { spacing: { before: 80, after: 80 } });
}
function blankLine() {
  return para([text("")], { spacing: { before: 40, after: 40 } });
}
function signatureLine(label) {
  return [
    para([text(label, { bold: true, size: 20 })], { spacing: { before: 200, after: 40 } }),
    para([text("Name: _________________________________________________")], { spacing: { after: 40 } }),
    para([text("Signature: _________________________________________________")], { spacing: { after: 40 } }),
    para([text("Date: _________________________________________________")], { spacing: { after: 120 } }),
  ];
}
function tableRow(cells, isHeader = false) {
  return new TableRow({
    tableHeader: isHeader,
    children: cells.map((c, i) => new TableCell({
      borders: cellBorders,
      width: { size: i === 0 ? 4680 : 4680, type: WidthType.DXA },
      shading: isHeader ? { fill: SAGE, type: ShadingType.CLEAR } : undefined,
      verticalAlign: VerticalAlign.CENTER,
      children: [para([text(c, isHeader ? { bold: true, color: "FFFFFF", size: 22 } : { size: 22 })], { alignment: AlignmentType.LEFT })]
    }))
  });
}
function bullets(items) {
  return items.map(item => new Paragraph({
    numbering: { reference: "bullet-list", level: 0 },
    children: [text(item)],
    spacing: { before: 40, after: 40 }
  }));
}

const doc = new Document({
  styles: {
    default: { document: { run: { font: FONT, size: 22 } } },
    paragraphStyles: [
      { id: "Heading1", name: "Heading 1", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 28, bold: true, color: DARK, font: FONT },
        paragraph: { spacing: { before: 360, after: 200 }, outlineLevel: 0 } },
    ]
  },
  numbering: {
    config: [
      { reference: "bullet-list",
        levels: [{ level: 0, format: LevelFormat.BULLET, text: "\u2022", alignment: AlignmentType.LEFT,
          style: { paragraph: { indent: { left: 720, hanging: 360 } } } }] },
    ]
  },
  sections: [{
    properties: { page: { margin: { top: 1440, right: 1440, bottom: 1440, left: 1440 } } },
    headers: { default: new Header({ children: [para([text("NURTURE INC.", { size: 16, color: SAGE, bold: true })], { alignment: AlignmentType.RIGHT })] }) },
    footers: { default: new Footer({ children: [para([
      text("Nurture Inc. | Independent Contractor Agreement | Page ", { size: 16, color: "999999" }),
      new TextRun({ children: [PageNumber.CURRENT], font: FONT, size: 16, color: "999999" }),
      text(" of ", { size: 16, color: "999999" }),
      new TextRun({ children: [PageNumber.TOTAL_PAGES], font: FONT, size: 16, color: "999999" }),
    ], { alignment: AlignmentType.CENTER })] }) },
    children: [
      // Title
      para([text("INDEPENDENT CONTRACTOR AGREEMENT", { bold: true, size: 36, color: DARK })], { alignment: AlignmentType.CENTER, spacing: { after: 80 } }),
      para([text("Property Operations Services", { size: 26, color: SAGE })], { alignment: AlignmentType.CENTER, spacing: { after: 400 } }),

      para([text("This Agreement is entered into as of _________________ (the \"Effective Date\")")], { spacing: { after: 200 } }),

      para([text("Between:", { bold: true, size: 24 })], { spacing: { after: 120 } }),
      para([text("Nurture Inc.", { bold: true }), text(" (\"the Company\")")], { spacing: { after: 40 } }),
      para([text("140 Simcoe St, Toronto, ON M5H 4E9")], { spacing: { after: 40 } }),
      para([text("Represented by: Jeff P, Owner")], { spacing: { after: 40 } }),
      para([text("Email: info@nurtre.io | Phone: (647) 957-8956")], { spacing: { after: 200 } }),

      para([text("And:", { bold: true, size: 24 })], { spacing: { after: 120 } }),
      para([text("Contractor Name: _________________________________________________")], { spacing: { after: 40 } }),
      para([text("Address: _________________________________________________")], { spacing: { after: 40 } }),
      para([text("Phone: _________________________________________________")], { spacing: { after: 40 } }),
      para([text("Email: _________________________________________________")], { spacing: { after: 300 } }),

      // 1. RELATIONSHIP
      heading("1. RELATIONSHIP"),
      subNum("1.1.", "The Contractor is engaged as an independent contractor, not an employee, partner, or agent of the Company. Nothing in this Agreement creates an employment relationship."),
      subNum("1.2.", "The Contractor is responsible for their own taxes, including income tax, HST/GST (if applicable), CPP, and EI. The Company will not withhold taxes or provide T4 slips. If the Contractor earns over $30,000 annually from all sources, they are responsible for registering for and remitting HST/GST."),
      subNum("1.3.", "The Contractor is not entitled to employee benefits, vacation pay, overtime, or any statutory entitlements reserved for employees under Ontario employment law."),

      // 2. SCOPE OF SERVICES
      heading("2. SCOPE OF SERVICES"),
      subNum("2.1.", "The Contractor agrees to provide property operations services for short-term and mid-term rental properties managed by the Company across the Greater Toronto Area, including but not limited to:"),
      ...bullets([
        "Post-cleaning quality inspections with photo documentation",
        "Guest supply restocking (toiletries, kitchen essentials, linens, cleaning supplies)",
        "Smart lock and lockbox installation, replacement, troubleshooting, battery replacement, and code management",
        "Coordination with and oversight of third-party maintenance providers",
        "On-site response to guest emergencies (lockouts, plumbing, appliance issues)",
        "Seasonal property preparation and light preventative maintenance",
        "New property onboarding, setup, and staging assistance",
        "Smartphone photo documentation during routine visits (inspections, maintenance issues, supply levels) as a standard part of all visits at no additional charge",
        "Professional property photography for listings (requires DSLR or mirrorless camera with wide-angle lens; smartphone photos are not acceptable for listing photography)",
        "Visit summary reporting and proactive maintenance flagging",
      ]),
      subNum("2.2.", "The Company will provide reasonable notice for scheduled visits. Emergency callouts may occur outside regular business hours with the Contractor's agreement."),
      subNum("2.3.", "The Contractor may decline any individual assignment without penalty, provided they communicate promptly. Consistent unavailability may result in termination under Section 10."),

      // 3. COMPENSATION
      heading("3. COMPENSATION"),
      subNum("3.1.", "The Contractor will be compensated as follows:"),
      new Table({
        columnWidths: [4680, 4680],
        rows: [
          tableRow(["Service Type", "Rate"], true),
          tableRow(["Scheduled property visit (inspection, restock, routine task)", "$50\u2013$65 per visit"]),
          tableRow(["Emergency callout (after 7pm or weekends/holidays)", "$75\u2013$100 per callout"]),
          tableRow(["New property setup/onboarding (half or full day)", "$200\u2013$350 per property"]),
          tableRow(["Professional photography session (listing photos)", "$150 per session"]),
          tableRow(["Out-of-GTA travel mileage", "CRA rate ($0.72/km first 5,000 km, $0.66/km after)"]),
          tableRow(["Supply purchasing (on behalf of Company)", "Reimbursed at cost + receipts"]),
        ]
      }),
      blankLine(),
      subNum("3.2.", "Payment schedule: Weekly, via Interac e-transfer, within 3 business days of the Contractor submitting a visit log for that week."),
      subNum("3.3.", "Visit logging: The Contractor will submit a weekly summary of all visits completed, including date, property address, type of visit, and any notes. A simple text message or shared spreadsheet is acceptable."),
      subNum("3.4.", "Supplies and materials: The Company will reimburse the Contractor for any supplies purchased on behalf of the Company, provided the purchase was pre-approved and accompanied by a receipt."),
      subNum("3.5.", "Mileage: The Contractor will not be reimbursed for fuel or vehicle costs for jobs within the Greater Toronto Area. For jobs outside the GTA (e.g., Midland, Niagara region, cottage country), the Company will reimburse mileage at the current CRA rate, calculated from the GTA boundary to the property and back. The Contractor must submit a mileage log with the distance and destination."),
      subNum("3.6.", "Rate review: Rates will be reviewed every 6 months or upon a significant change in the number of managed properties, whichever comes first."),

      // 4. PROPERTY ACCESS AND SECURITY
      heading("4. PROPERTY ACCESS AND SECURITY"),
      subNum("4.1.", "The Company will provide the Contractor with access credentials (lock codes, smart lock access, physical keys, or lockbox combinations) for properties as needed."),
      subNum("4.2.", "The Contractor agrees to:"),
      ...bullets([
        "Never share access codes, keys, or credentials with any third party",
        "Never allow unauthorized persons to enter a managed property",
        "Secure all entry points upon leaving a property",
        "Return all physical keys and delete all stored codes upon termination of this Agreement",
        "Report any lost keys, compromised codes, or security concerns to the Company immediately",
      ]),
      subNum("4.3.", "The Company reserves the right to change access credentials at any time and for any reason."),
      subNum("4.4.", "The Contractor will never enter a property while a guest is present without explicit guest consent and Company authorization, except in genuine emergencies involving safety."),

      // 5. CONFIDENTIALITY
      heading("5. CONFIDENTIALITY"),
      subNum("5.1.", "The Contractor will have access to confidential information including but not limited to: property addresses, owner details, guest information, booking data, pricing strategies, financial information, and business operations."),
      subNum("5.2.", "The Contractor agrees to:"),
      ...bullets([
        "Keep all confidential information strictly private",
        "Never disclose property owner names, contact details, or financial information to any third party",
        "Never disclose guest names, contact details, or booking information to any third party",
        "Never share the Company's pricing, revenue, or operational data",
        "Never use confidential information for personal gain or to compete with the Company",
      ]),
      subNum("5.3.", "This confidentiality obligation survives termination of this Agreement and remains in effect indefinitely."),

      // 6. LIABILITY AND INSURANCE
      heading("6. LIABILITY AND INSURANCE"),
      subNum("6.1.", "The Contractor carries out services at their own risk. The Company is not responsible for injuries sustained by the Contractor while performing services."),
      subNum("6.2.", "The Contractor agrees to exercise reasonable care when accessing and working in managed properties. The Contractor will be held financially responsible for any damage to a property, its contents, or guest belongings caused by the Contractor's negligence or misconduct."),
      subNum("6.3.", "The Contractor is strongly encouraged to carry their own general liability insurance. If the Contractor does carry insurance, a copy of the certificate should be provided to the Company."),
      subNum("6.4.", "The Contractor agrees to maintain valid auto insurance on any vehicle used for service-related travel."),
      subNum("6.5.", "The Company carries its own commercial general liability insurance covering managed properties. This coverage does not extend to the Contractor's personal liability."),

      // 7. CLIENT COMMUNICATION BOUNDARIES
      heading("7. CLIENT COMMUNICATION BOUNDARIES"),
      subNum("7.1.", "The Contractor will represent the Company (Nurture) at all times when interacting with property owners, guests, or third parties. The Contractor will never represent themselves as an independent operator or promote any personal business during Company assignments."),
      subNum("7.2.", "All communication with property owners must go through the Company. The Contractor will not:"),
      ...bullets([
        "Contact property owners directly outside of Company-authorized channels (e.g., group chats that include Company management)",
        "Provide personal phone numbers, email addresses, or social media accounts to property owners",
        "Discuss management fees, commission structures, revenue figures, or any financial details with property owners",
        "Offer personal services, advice, or opinions on property management strategy to property owners",
        "Accept gifts, tips, or side payments from property owners without disclosing them to the Company",
      ]),
      subNum("7.3.", "If a property owner asks the Contractor about pricing, contract terms, service changes, or any business matter, the Contractor will respond: \"I'll have our management team get back to you on that.\""),
      subNum("7.4.", "During client onboarding or property owner meetings, the Contractor will attend only when directed by the Company, will follow the Company's onboarding procedures, and will present themselves as a member of the Nurture operations team."),
      subNum("7.5.", "The Contractor will not initiate, maintain, or develop personal or business relationships with property owners outside of the scope of their duties under this Agreement."),

      // 8. INTELLECTUAL PROPERTY
      heading("8. INTELLECTUAL PROPERTY"),
      subNum("8.1.", "The Company's client list, property owner contacts, property details, pricing strategies, standard operating procedures, software tools, automations, and business processes are proprietary and constitute trade secrets."),
      subNum("8.2.", "The Contractor acknowledges that exposure to the Company's clients and business methods does not entitle them to use that information for any purpose other than fulfilling their obligations under this Agreement."),
      subNum("8.3.", "Upon termination of this Agreement, the Contractor will not retain, copy, or use any Company information, including but not limited to: property owner names and contact information, property addresses and access details, guest data, pricing data, operational procedures, or any other business information obtained during the term of this Agreement."),
      subNum("8.4.", "All photographs, videos, and media produced by the Contractor during the course of their engagement are the exclusive property of the Company. The Contractor may not use, publish, or share any media captured at Company-managed properties for personal or commercial purposes."),

      // 9. CONDUCT AND STANDARDS
      heading("9. CONDUCT AND STANDARDS"),
      subNum("9.1.", "The Contractor will perform all services in a professional, courteous, and timely manner."),
      subNum("9.2.", "When interacting with guests (in person, by phone, or by message), the Contractor will represent the Company positively and refrain from making commitments, promises, or refund offers without Company authorization."),
      subNum("9.3.", "The Contractor will not consume alcohol or use recreational substances while performing services at any managed property."),
      subNum("9.4.", "The Contractor will not bring unauthorized persons (friends, family, pets) to managed properties during service visits."),
      subNum("9.5.", "The Contractor will comply with all applicable laws and regulations while performing services."),

      // 10. TERM AND TERMINATION
      heading("10. TERM AND TERMINATION"),
      subNum("10.1.", "This Agreement begins on the Effective Date and continues on a month-to-month basis until terminated by either party."),
      subNum("10.2.", "Termination by either party: Either party may terminate this Agreement with 14 days' written notice (email is acceptable) for any reason or no reason."),
      subNum("10.3.", "Immediate termination: The Company may terminate this Agreement immediately and without notice in the event of:"),
      ...bullets([
        "Theft, fraud, or dishonesty",
        "Damage to property caused by negligence or misconduct",
        "Breach of confidentiality (Section 5)",
        "Breach of client communication boundaries (Section 7)",
        "Sharing or misusing property access credentials",
        "Conduct that harms the Company's reputation or client relationships",
        "Failure to respond to an accepted emergency callout without explanation",
      ]),
      subNum("10.4.", "Upon termination, the Contractor will:"),
      ...bullets([
        "Return all physical keys, devices, and Company property within 48 hours",
        "Delete all stored access codes and credentials from personal devices",
        "Delete all property owner contact information from personal devices and accounts",
        "Submit a final visit log for any unpaid work",
        "The Company will pay all outstanding amounts within 7 business days of receiving the final visit log",
      ]),

      // 11. NON-SOLICITATION AND NON-COMPETE
      heading("11. NON-SOLICITATION AND NON-COMPETE"),
      subNum("11.1.", "During the term of this Agreement and for 24 months following termination, the Contractor agrees not to:"),
      ...bullets([
        "Directly or indirectly solicit, contact, or accept property management, co-hosting, or short-term/mid-term rental management work from any property owner whose property is or was managed by the Company during the Contractor's engagement",
        "Encourage, advise, or assist any property owner in terminating their agreement with the Company",
        "Provide property management, co-hosting, or rental optimization services to any property owner who was a client of the Company at any point during the Contractor's engagement, whether or not the property owner is still a client at the time of solicitation",
        "Use any information obtained during their engagement (property owner contacts, property details, guest data, pricing strategies) to solicit business from the Company's clients, former clients, or prospective clients",
      ]),
      subNum("11.2.", "During the term of this Agreement and for 12 months following termination, the Contractor agrees not to operate, co-host, or manage short-term or mid-term rental properties within the Greater Toronto Area that directly compete with the Company's services, using knowledge, contacts, or methods obtained during their engagement with the Company."),
      subNum("11.3.", "This does not prevent the Contractor from performing general handyman, cleaning, or maintenance work for any party, provided it does not involve short-term or mid-term rental management services for the Company's current or former clients."),
      subNum("11.4.", "Liquidated Damages. The parties acknowledge that a breach of this Section would cause significant and difficult-to-quantify harm to the Company, including lost revenue, client acquisition costs, and reputational damage. In the event the Contractor breaches any provision of this Section, the Contractor agrees to pay the Company liquidated damages equal to $10,000 per property owner solicited, contacted, or serviced in violation of this Section, plus the equivalent of 12 months of management fees that the Company would have earned from each affected property, calculated based on the average monthly management fee earned from that property during the 6 months preceding the breach. These liquidated damages are in addition to, and not a substitute for, any other legal remedies available to the Company, including injunctive relief."),
      subNum("11.5.", "The Contractor acknowledges that they have read and understood this Section, that the restrictions are reasonable in scope and duration given the nature of the Company's business and the Contractor's access to confidential information and client relationships, and that the liquidated damages amount represents a genuine pre-estimate of the Company's losses in the event of a breach."),

      // 12. BACKGROUND CHECK
      heading("12. BACKGROUND CHECK"),
      subNum("12.1.", "The Contractor consents to a criminal background check prior to being granted property access. The Company will cover the cost of this check."),
      subNum("12.2.", "A clear background check is a condition of this Agreement. Certain findings may, at the Company's discretion, prevent or terminate the engagement."),

      // 13. GENERAL
      heading("13. GENERAL"),
      subNum("13.1.", "This Agreement constitutes the entire agreement between the parties and supersedes all prior discussions or agreements."),
      subNum("13.2.", "This Agreement is governed by the laws of the Province of Ontario and the federal laws of Canada applicable therein."),
      subNum("13.3.", "Amendments to this Agreement must be in writing and signed by both parties."),
      subNum("13.4.", "If any provision of this Agreement is found to be unenforceable, the remaining provisions will continue in full force and effect."),
      subNum("13.5.", "The Contractor may not assign or subcontract any obligations under this Agreement without the Company's written consent."),

      // SIGNATURES
      para([text("")], { spacing: { before: 400 } }),
      para([text("SIGNATURES", { bold: true, size: 28, color: DARK })], { alignment: AlignmentType.CENTER, spacing: { after: 120 } }),
      para([text("By signing below, both parties agree to the terms set out in this Agreement.")], { alignment: AlignmentType.CENTER, spacing: { after: 200 } }),

      para([text("For the Company:", { bold: true, size: 24, color: DARK })], { spacing: { before: 200, after: 80 } }),
      ...signatureLine("Company Representative"),

      para([text("Contractor:", { bold: true, size: 24, color: DARK })], { spacing: { before: 300, after: 80 } }),
      ...signatureLine("Contractor"),

      blankLine(),
      para([text("This document is a template and does not constitute legal advice. Both parties are encouraged to seek independent legal counsel before signing.", { italics: true, size: 18, color: "999999" })], { alignment: AlignmentType.CENTER, spacing: { before: 400 } }),
    ]
  }]
});

Packer.toBuffer(doc).then(buffer => {
  fs.writeFileSync("docs/hiring/ops-contractor-agreement.docx", buffer);
  console.log("Created docs/hiring/ops-contractor-agreement.docx");
});
