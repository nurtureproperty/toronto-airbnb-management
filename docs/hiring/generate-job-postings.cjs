const fs = require("fs");
const { Document, Packer, Paragraph, TextRun, Header, Footer, AlignmentType, LevelFormat, HeadingLevel, BorderStyle, WidthType, ShadingType, VerticalAlign, Table, TableRow, TableCell } = require("docx");

const FONT = "Arial";
const SAGE = "759B8F";
const DARK = "5A7D73";

function text(t, opts = {}) {
  return new TextRun({ text: t, font: FONT, size: opts.size || 22, ...opts });
}
function para(children, opts = {}) {
  return new Paragraph({ children: Array.isArray(children) ? children : [children], ...opts });
}
function heading(t) {
  return new Paragraph({ heading: HeadingLevel.HEADING_1, children: [text(t, { bold: true, size: 28, color: DARK })] });
}
function bullet(t) {
  return new Paragraph({ numbering: { reference: "bl", level: 0 }, children: [text(t)], spacing: { before: 40, after: 40 } });
}
function numItem(t) {
  return new Paragraph({ numbering: { reference: "nl", level: 0 }, children: [text(t)], spacing: { before: 40, after: 40 } });
}

const numberingConfig = {
  config: [
    { reference: "bl", levels: [{ level: 0, format: LevelFormat.BULLET, text: "\u2022", alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 720, hanging: 360 } } } }] },
    { reference: "nl", levels: [{ level: 0, format: LevelFormat.DECIMAL, text: "%1.", alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 720, hanging: 360 } } } }] },
  ]
};
const pageProps = { page: { margin: { top: 1440, right: 1440, bottom: 1440, left: 1440 } } };
const hdr = new Header({ children: [para([text("NURTURE INC.", { size: 16, color: SAGE, bold: true })], { alignment: AlignmentType.RIGHT })] });
const ftr = new Footer({ children: [para([text("Nurture Inc. | Job Posting", { size: 16, color: "999999" })], { alignment: AlignmentType.CENTER })] });
const tblBorder = { style: BorderStyle.SINGLE, size: 1, color: "CCCCCC" };
const tblBorders = { top: tblBorder, bottom: tblBorder, left: tblBorder, right: tblBorder };
function tCell(t, opts = {}) {
  return new TableCell({ borders: tblBorders, width: { size: opts.width || 3120, type: WidthType.DXA }, shading: opts.header ? { fill: SAGE, type: ShadingType.CLEAR } : undefined, verticalAlign: VerticalAlign.CENTER, children: [para([text(t, opts.header ? { bold: true, color: "FFFFFF", size: 20 } : { size: 20 })])] });
}
function tRow(cells, header = false) {
  return new TableRow({ tableHeader: header, children: cells.map(c => tCell(c.t, { width: c.w, header })) });
}

// ===================== KIJIJI =====================
const kijiji = new Document({
  styles: { default: { document: { run: { font: FONT, size: 22 } } },
    paragraphStyles: [{ id: "Heading1", name: "Heading 1", basedOn: "Normal", next: "Normal", quickFormat: true, run: { size: 28, bold: true, color: DARK, font: FONT }, paragraph: { spacing: { before: 360, after: 200 }, outlineLevel: 0 } }]
  },
  numbering: numberingConfig,
  sections: [{
    properties: pageProps, headers: { default: hdr }, footers: { default: ftr },
    children: [
      para([text("Property Operations Assistant (Contract)", { bold: true, size: 36, color: DARK })], { alignment: AlignmentType.CENTER, spacing: { after: 80 } }),
      para([text("Airbnb Management Company, GTA", { size: 26, color: SAGE })], { alignment: AlignmentType.CENTER, spacing: { after: 400 } }),

      para([text("We're Nurture, a growing Airbnb management company based in Toronto managing 15+ short-term and mid-term rental properties across the GTA. We're looking for two reliable, detail-oriented contractors to help with on-the-ground property operations.")], { spacing: { after: 120 } }),
      para([text("This is not a desk job. You'll be the person we call when a property needs eyes on it: quality checks after cleanings, supply drops, guest lockouts, smart lock installs, letting in a plumber, or handling the occasional 10pm \"the toilet won't stop running\" situation.")], { spacing: { after: 200 } }),

      heading("What You'd Be Doing"),
      bullet("Post-cleaning quality inspections (checking that units are guest-ready, smartphone photo documentation)"),
      bullet("Restocking supplies (toiletries, coffee, linens, cleaning products)"),
      bullet("Smart lock installation, replacement, troubleshooting, battery swaps, and code resets"),
      bullet("Coordinating with maintenance pros (letting them in, overseeing small repairs)"),
      bullet("Handling guest emergencies that need someone physically present"),
      bullet("Seasonal property prep (AC filters, winter supplies, patio setup)"),
      bullet("New property setup and staging assistance"),
      bullet("Assisting with in-person client onboarding as part of our operations team"),
      bullet("Professional property photography for new listings (paid separately, requires DSLR or mirrorless camera with wide-angle lens)"),

      heading("What Makes You a Great Fit"),
      bullet("You live in the GTA (Toronto, Scarborough, North York, Etobicoke, or nearby)"),
      bullet("You have a reliable car and valid G license"),
      bullet("You're handy enough to unclog a drain, reset a breaker, install a smart lock, or tighten a loose handle"),
      bullet("You own a smartphone and can send photos, reply to texts, and use basic apps"),
      bullet("You're available for occasional evening or weekend emergency calls"),
      bullet("You're trustworthy and comfortable with independent property access"),
      bullet("You notice the details: a missing towel, a scuff on the wall, a lightbulb that's out"),
      bullet("You're professional and presentable (you may meet property owners face to face)"),

      heading("Pay and Structure"),
      bullet("$50 to $65 per property visit (depending on scope)"),
      bullet("$75 to $100 for after-hours emergency callouts"),
      bullet("$200 to $350 for new property setup/onboarding"),
      bullet("$150 per professional photography session (must have DSLR/mirrorless with wide-angle lens)"),
      bullet("Supply purchases reimbursed at cost with receipts"),
      bullet("Paid weekly via e-transfer"),
      bullet("Estimated 10 to 15 visits per month per contractor (this will grow as we add properties)"),
      bullet("Fully flexible schedule for routine visits, you set your own availability"),
      para([text("")], { spacing: { after: 40 } }),
      para([text("This is a contract position, not employment. You set your own hours for routine tasks. We coordinate with you on scheduling, and you're reachable for urgent calls during agreed hours. No office, no commute, no micromanagement.")], { spacing: { after: 120 } }),
      para([text("Most work is within the GTA, but occasional jobs outside the area (e.g., Midland, Niagara region) will come up. For trips outside the GTA, mileage is paid at the CRA rate ($0.72/km for the first 5,000 km).")], { spacing: { after: 200 } }),

      heading("Bonus Points If You"),
      bullet("Have experience in Airbnb hosting, property management, or hospitality"),
      bullet("Own a DSLR or mirrorless camera with a wide-angle lens"),
      bullet("Can handle basic furniture assembly or minor repairs"),
      bullet("Speak more than one language"),
      bullet("Are interested in growing with us as we scale"),

      heading("How to Apply"),
      para([text("Send a message that includes:", { bold: true })], { spacing: { after: 80 } }),
      numItem("Where you live (neighborhood or city)"),
      numItem("What type of car you drive"),
      numItem("A brief note on any relevant experience (even if it's managing your own rental or doing handyman work)"),
      numItem("Use the word \"Nurture\" somewhere in your message"),
      para([text("")], { spacing: { after: 80 } }),
      para([text("Applications that don't include all four items will not be reviewed.", { bold: true, color: DARK })]),
    ]
  }]
});

// ===================== INDEED =====================
const indeed = new Document({
  styles: { default: { document: { run: { font: FONT, size: 22 } } },
    paragraphStyles: [{ id: "Heading1", name: "Heading 1", basedOn: "Normal", next: "Normal", quickFormat: true, run: { size: 28, bold: true, color: DARK, font: FONT }, paragraph: { spacing: { before: 360, after: 200 }, outlineLevel: 0 } }]
  },
  numbering: numberingConfig,
  sections: [{
    properties: pageProps, headers: { default: hdr }, footers: { default: ftr },
    children: [
      para([text("Property Operations Contractor", { bold: true, size: 36, color: DARK })], { alignment: AlignmentType.CENTER, spacing: { after: 80 } }),
      para([text("Short-Term Rental Management (GTA)", { size: 26, color: SAGE })], { alignment: AlignmentType.CENTER, spacing: { after: 200 } }),

      para([text("Company: ", { bold: true }), text("Nurture Property Management")], { spacing: { after: 40 } }),
      para([text("Location: ", { bold: true }), text("Greater Toronto Area (mobile, multi-site) with occasional travel outside GTA")], { spacing: { after: 40 } }),
      para([text("Type: ", { bold: true }), text("Independent Contractor")], { spacing: { after: 40 } }),
      para([text("Compensation: ", { bold: true }), text("$50 to $65 per visit | $75 to $100 emergency callout | Mileage paid for out-of-GTA jobs")], { spacing: { after: 200 } }),

      heading("About Us"),
      para([text("Nurture is a Toronto-based Airbnb and short-term rental management company. We manage 15+ properties across the GTA (with some properties in areas like Midland and Niagara) and are growing quickly. We're hiring two Property Operations Contractors to handle on-site property operations as we scale, each covering a different area of the GTA.")], { spacing: { after: 200 } }),

      heading("Role Overview"),
      para([text("As our Property Operations Contractor, you'll be responsible for the physical upkeep and guest-readiness of our managed rental properties. This is a mobile, field-based role. You'll visit properties across the GTA for scheduled tasks and respond to urgent situations as they arise.")], { spacing: { after: 80 } }),
      para([text("This is also a client-facing role. You'll occasionally assist with in-person property onboarding and meet property owners as part of our operations team. Occasional trips outside the GTA are required, with mileage compensation at the CRA rate.")], { spacing: { after: 200 } }),

      heading("Responsibilities"),
      bullet("Conduct post-cleaning quality inspections with smartphone photo documentation"),
      bullet("Restock guest supplies (toiletries, kitchen essentials, linens)"),
      bullet("Install, replace, troubleshoot, and maintain smart locks, lockboxes, and access systems"),
      bullet("Coordinate with and oversee third-party maintenance providers"),
      bullet("Respond to on-site guest emergencies (lockouts, appliance failures, plumbing issues)"),
      bullet("Perform seasonal property preparation and light preventative maintenance"),
      bullet("Assist with new property onboarding, setup, and staging"),
      bullet("Attend client meetings when directed, representing the Nurture operations team"),
      bullet("Professional property photography for new listings (paid separately at $150/session, requires professional camera equipment)"),
      bullet("Provide visit summaries and flag maintenance concerns proactively"),

      heading("Requirements"),
      bullet("Located in the GTA with a reliable personal vehicle and valid G license"),
      bullet("Able to install and replace smart locks on standard residential doors"),
      bullet("Available for occasional evening and weekend emergency response"),
      bullet("Comfortable with independent property access and working unsupervised"),
      bullet("Basic handyman skills (minor repairs, troubleshooting common household issues)"),
      bullet("Smartphone with camera for routine documentation and communication"),
      bullet("Strong attention to detail and accountability"),
      bullet("Professional and presentable for client-facing interactions"),
      bullet("Willing to travel outside the GTA occasionally (mileage compensated)"),
      bullet("Clear criminal background (background check required before property access)"),

      heading("Preferred"),
      bullet("Experience in property management, Airbnb hosting, or hospitality"),
      bullet("Own a DSLR or mirrorless camera with wide-angle lens (for paid photography sessions)"),
      bullet("Bilingual or multilingual"),
      bullet("Basic furniture assembly and staging experience"),
      bullet("Located in one of these areas: Downtown/Midtown Toronto, Scarborough/East York, or North York/Etobicoke"),

      heading("Compensation"),
      bullet("$50 to $65 per scheduled property visit"),
      bullet("$75 to $100 per emergency callout (after hours)"),
      bullet("$200 to $350 per new property setup/onboarding"),
      bullet("$150 per professional photography session (requires DSLR/mirrorless with wide-angle lens)"),
      bullet("Mileage at CRA rate ($0.72/km) for jobs outside the GTA"),
      bullet("Supply purchases reimbursed at cost with receipts"),
      bullet("Weekly payment via e-transfer"),
      bullet("Estimated 10 to 15 visits per month, increasing with portfolio growth"),

      heading("How to Apply"),
      para([text("Submit a message or resume that includes:", { bold: true })], { spacing: { after: 80 } }),
      numItem("Where in the GTA you are based (neighborhood or city)"),
      numItem("What type of vehicle you drive"),
      numItem("Any relevant experience (property management, Airbnb hosting, handyman, hospitality, cleaning)"),
      numItem("Include the word \"Nurture\" in your application"),
      para([text("")], { spacing: { after: 80 } }),
      para([text("Applications missing any of the four items above will not be considered.", { bold: true, color: DARK })]),
    ]
  }]
});

// ===================== SCREENING GUIDE =====================
const screening = new Document({
  styles: { default: { document: { run: { font: FONT, size: 22 } } },
    paragraphStyles: [
      { id: "Heading1", name: "Heading 1", basedOn: "Normal", next: "Normal", quickFormat: true, run: { size: 28, bold: true, color: DARK, font: FONT }, paragraph: { spacing: { before: 360, after: 200 }, outlineLevel: 0 } },
      { id: "Heading2", name: "Heading 2", basedOn: "Normal", next: "Normal", quickFormat: true, run: { size: 24, bold: true, color: DARK, font: FONT }, paragraph: { spacing: { before: 240, after: 160 }, outlineLevel: 1 } },
    ]
  },
  numbering: numberingConfig,
  sections: [{
    properties: pageProps, headers: { default: hdr }, footers: { default: ftr },
    children: [
      para([text("Ops Contractor Screening Guide", { bold: true, size: 36, color: DARK })], { alignment: AlignmentType.CENTER, spacing: { after: 80 } }),
      para([text("Internal Document", { size: 22, color: SAGE, italics: true })], { alignment: AlignmentType.CENTER, spacing: { after: 400 } }),

      heading("Stage 1: Application Filter"),
      para([text("Auto-reject if:", { bold: true })], { spacing: { after: 80 } }),
      bullet("Missing location, car type, or the word \"Nurture\""),
      bullet("Generic copy/paste message with no specifics"),
      bullet("Located more than 45 minutes from your property clusters"),
      para([text("Green flags:", { bold: true })], { spacing: { before: 120, after: 80 } }),
      bullet("Mentions specific Airbnb or property management experience"),
      bullet("Detailed message showing they read the posting"),
      bullet("Lives centrally in the GTA"),
      bullet("Owns a reliable vehicle (not \"I take transit\")"),
      bullet("Mentions owning professional camera equipment"),
      bullet("Has smart lock installation experience"),

      heading("Stage 2: Text Message Screen"),
      para([text("Send this to applicants who pass Stage 1:")], { spacing: { after: 80 } }),
      para([text("\"Thanks for applying to the Nurture ops contractor role. Quick scenario for you:", { italics: true })], { spacing: { after: 40 }, indent: { left: 360 } }),
      para([text("You're doing a post-clean quality check at one of our Airbnb properties. You walk in and notice: the bathroom mirror has water spots, a throw pillow is missing from the couch, and the wifi router is unplugged. Guest checks in at 4pm today. It's 1pm now. What do you do?\"", { italics: true })], { spacing: { after: 200 }, indent: { left: 360 } }),
      para([text("Scoring:", { bold: true })], { spacing: { after: 80 } }),
      new Table({
        columnWidths: [2800, 3280, 3280],
        rows: [
          tRow([{ t: "What to Look For", w: 2800 }, { t: "Good Answer", w: 3280 }, { t: "Red Flag", w: 3280 }], true),
          tRow([{ t: "Response time", w: 2800 }, { t: "Within a few hours", w: 3280 }, { t: "2+ days", w: 3280 }]),
          tRow([{ t: "Addresses all 3 issues", w: 2800 }, { t: "Yes, in order of priority", w: 3280 }, { t: "Only mentions one", w: 3280 }]),
          tRow([{ t: "Takes initiative", w: 2800 }, { t: "Cleans mirror, checks for pillow, plugs in router", w: 3280 }, { t: "\"I'd call you and ask what to do\"", w: 3280 }]),
          tRow([{ t: "Photo documentation", w: 2800 }, { t: "Mentions taking photos before/after", w: 3280 }, { t: "No mention", w: 3280 }]),
          tRow([{ t: "Communication", w: 2800 }, { t: "Texts summary of what they found and fixed", w: 3280 }, { t: "Radio silence", w: 3280 }]),
          tRow([{ t: "Guest awareness", w: 2800 }, { t: "Notes 4pm deadline, prioritizes", w: 3280 }, { t: "No urgency", w: 3280 }]),
        ]
      }),
      para([text("")], { spacing: { after: 80 } }),
      para([text("Ideal answer sounds something like:", { bold: true })], { spacing: { after: 80 } }),
      para([text("\"I'd plug the router back in first since wifi is essential for guests. Clean the water spots off the mirror myself (takes 30 seconds). For the missing pillow, I'd check the closets and laundry area. If I can't find it, I'd text you right away with a photo of the couch so you can decide if we need a replacement before 4pm. I'd take photos of everything I flagged and send you a quick summary.\"", { italics: true })], { spacing: { after: 200 }, indent: { left: 360 } }),

      heading("Stage 3: Paid Trial Visit ($65)"),
      new Paragraph({ heading: HeadingLevel.HEADING_2, children: [text("Setup", { bold: true, size: 24, color: DARK })] }),
      para([text("Pick a property between guest stays. Plant 5 intentional issues:")], { spacing: { after: 80 } }),
      numItem("Towel on the bathroom floor"),
      numItem("Coffee maker unplugged"),
      numItem("Expired item in the fridge"),
      numItem("One lightbulb out (bathroom or bedroom)"),
      numItem("TV remote in a weird spot (under a cushion or on the kitchen counter)"),

      new Paragraph({ heading: HeadingLevel.HEADING_2, children: [text("Instructions to Candidate", { bold: true, size: 24, color: DARK })] }),
      para([text("\"I need you to do a post-clean inspection at [address]. Here's the lock code. Walk through the entire unit and send me a photo walkthrough of anything you'd flag or fix. Text me when you're done.\"", { italics: true })], { spacing: { after: 200 }, indent: { left: 360 } }),

      new Paragraph({ heading: HeadingLevel.HEADING_2, children: [text("Scoring", { bold: true, size: 24, color: DARK })] }),
      new Table({
        columnWidths: [4680, 4680],
        rows: [
          tRow([{ t: "Criteria", w: 4680 }, { t: "Scoring", w: 4680 }], true),
          tRow([{ t: "On time", w: 4680 }, { t: "Pass/fail", w: 4680 }]),
          tRow([{ t: "Figured out lock without excessive help", w: 4680 }, { t: "Pass/fail", w: 4680 }]),
          tRow([{ t: "Found 4 or 5 of 5 planted issues", w: 4680 }, { t: "Strong hire", w: 4680 }]),
          tRow([{ t: "Found 3 of 5", w: 4680 }, { t: "Acceptable", w: 4680 }]),
          tRow([{ t: "Found 2 or fewer", w: 4680 }, { t: "Pass", w: 4680 }]),
          tRow([{ t: "Photo quality (clear, well-lit, shows issue)", w: 4680 }, { t: "Rate 1 to 5", w: 4680 }]),
          tRow([{ t: "Report detail (summary text, not just photos)", w: 4680 }, { t: "Rate 1 to 5", w: 4680 }]),
          tRow([{ t: "Locked up properly when leaving", w: 4680 }, { t: "Pass/fail", w: 4680 }]),
        ]
      }),
      para([text("")], { spacing: { after: 80 } }),
      para([text("Bonus points:", { bold: true })], { spacing: { after: 80 } }),
      bullet("Fixed things on the spot (plugged in coffee maker, moved towel, replaced lightbulb)"),
      bullet("Noticed something you DIDN'T plant (actual issue with the property)"),
      bullet("Sent a clean summary text without being asked twice"),

      heading("Stage 4: Shadow Week"),
      bullet("3 to 5 property visits where they ride along with you"),
      bullet("Visit 1 and 2: they watch you, you explain your process"),
      bullet("Visit 3: they lead, you observe and give feedback"),
      bullet("Visit 4 and 5: they go solo, you review their photo reports after"),
      para([text("")], { spacing: { after: 80 } }),
      para([text("Evaluate:", { bold: true })], { spacing: { after: 80 } }),
      bullet("Do they follow the process you showed them?"),
      bullet("Are they asking good questions or just nodding?"),
      bullet("How do they interact if they encounter a cleaner or guest?"),
      bullet("Are their solo reports thorough?"),
      bullet("Would you trust them alone in a client's home?"),

      heading("Final Decision"),
      para([text("Hire 2 contractors, split by geography:")], { spacing: { after: 80 } }),
      bullet("Contractor A: your densest property area (primary, 70% of visits)"),
      bullet("Contractor B: your secondary area (backup, 30% of visits + emergency priority)"),
      bullet("Both serve as backup for each other"),
      bullet("Adjust split based on performance over the first month"),
    ]
  }]
});

async function generate() {
  const k = await Packer.toBuffer(kijiji);
  fs.writeFileSync("docs/hiring/ops-contractor-job-posting-kijiji.docx", k);
  console.log("Created ops-contractor-job-posting-kijiji.docx");

  const i = await Packer.toBuffer(indeed);
  fs.writeFileSync("docs/hiring/ops-contractor-job-posting-indeed.docx", i);
  console.log("Created ops-contractor-job-posting-indeed.docx");

  const s = await Packer.toBuffer(screening);
  fs.writeFileSync("docs/hiring/ops-contractor-screening-guide.docx", s);
  console.log("Created ops-contractor-screening-guide.docx");
}
generate();
