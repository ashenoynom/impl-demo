// Symposium deck: Nominal spacecraft dev & ops use cases
// Theme: mission-console dark — deep space navy, signal green accent,
// monospace eyebrow motif. Image-forward, minimal words.
const pptxgen = require("pptxgenjs");

const BG = "0B1120";
const CARD = "15203A";
const CARD_EDGE = "1D2A47";
const TEXT = "E8EEF9";
const MUTED = "8FA3C4";
const GREEN = "2ED47A";
const RED = "E4574F";

const HEAD = "Arial";
const BODY = "Calibri";
const MONO = "Courier New";

const pres = new pptxgen();
pres.layout = "LAYOUT_WIDE"; // 13.33 x 7.5
pres.defineSlideMaster({ title: "DARK", background: { color: BG } });

const IMG_RATIO = 1920 / 1052; // cropped app windows
const TVAC_RATIO = 3024 / 1722;

function eyebrow(slide, text) {
  slide.addText(text, {
    x: 0.6, y: 0.5, w: 12.1, h: 0.3, margin: 0,
    fontFace: MONO, fontSize: 12, color: GREEN, charSpacing: 2,
  });
}

function slideTitle(slide, text) {
  slide.addText(text, {
    x: 0.6, y: 0.82, w: 12.1, h: 0.75, margin: 0,
    fontFace: HEAD, fontSize: 30, bold: true, color: TEXT,
  });
}

function pageNum(slide, n) {
  slide.addText(`NOMINAL / ${String(n).padStart(2, "0")}`, {
    x: 11.6, y: 7.08, w: 1.6, h: 0.25, margin: 0, align: "right",
    fontFace: MONO, fontSize: 8, color: MUTED,
  });
}

function bullets(slide, items, x, w) {
  slide.addText(
    items.map((t, i) => ({
      text: t,
      options: {
        bullet: { code: "2022", indent: 14 },
        breakLine: i !== items.length - 1,
        paraSpaceAfter: 14,
      },
    })),
    { x, y: 2.15, w, h: 4.4, margin: 0, fontFace: BODY, fontSize: 14.5, color: TEXT, valign: "top" }
  );
}

function shot(slide, path, x, ratio = IMG_RATIO) {
  const w = 7.55, h = w / ratio;
  const y = 2.15;
  slide.addShape("roundRect", {
    x: x - 0.06, y: y - 0.06, w: w + 0.12, h: h + 0.12,
    fill: { color: CARD_EDGE }, rectRadius: 0.06, line: { type: "none" },
  });
  slide.addImage({ path, x, y, w, h });
}

// ---------------------------------------------------------------- 1 title
let s = pres.addSlide({ masterName: "DARK" });
s.addText("NOMINAL // SPACECRAFT DEV & OPS", {
  x: 0.75, y: 2.35, w: 11.8, h: 0.35, margin: 0,
  fontFace: MONO, fontSize: 14, color: GREEN, charSpacing: 3,
});
s.addText("From TVAC to orbit.", {
  x: 0.7, y: 2.75, w: 11.9, h: 1.1, margin: 0,
  fontFace: HEAD, fontSize: 54, bold: true, color: TEXT,
});
s.addText(
  "One data platform across the spacecraft lifecycle — integration & test, software upgrades, commissioning, fleet operations, and anomaly response.",
  { x: 0.75, y: 4.0, w: 9.8, h: 0.8, margin: 0, fontFace: BODY, fontSize: 17, color: MUTED }
);
s.addText("Live demo environment: 25-satellite GOCE constellation · app.gov.nominal.io", {
  x: 0.75, y: 6.85, w: 9.5, h: 0.3, margin: 0, fontFace: MONO, fontSize: 10, color: MUTED,
});

// ---------------------------------------------------------------- 2 breadth
s = pres.addSlide({ masterName: "DARK" });
eyebrow(s, "THE PITCH / BREADTH");
slideTitle(s, "Everything between the chamber and the constellation");
const stages = [
  ["01", "Integration & test", "TVAC, EMI, bench DAQ — campaign data lands next to flight data, forever queryable"],
  ["02", "Software & FSW", "Upgrade campaigns — trend behavior before vs after, across every satellite"],
  ["03", "Commissioning", "Checkout runs, automated data reviews, review-by-exception"],
  ["04", "Fleet operations", "Live limits, alerting to Slack/paging, durable events on the asset timeline"],
  ["05", "Anomaly response", "RCA workbooks, run comparison, procedures that command and verify"],
];
stages.forEach(([num, name, desc], i) => {
  const x = 0.6 + i * 2.47;
  s.addShape("roundRect", { x, y: 2.3, w: 2.28, h: 3.5, fill: { color: CARD }, rectRadius: 0.08, line: { type: "none" } });
  s.addText(num, { x: x + 0.2, y: 2.55, w: 1.8, h: 0.35, margin: 0, fontFace: MONO, fontSize: 15, color: GREEN, bold: true });
  s.addText(name, { x: x + 0.2, y: 2.95, w: 1.95, h: 0.75, margin: 0, fontFace: HEAD, fontSize: 15, bold: true, color: TEXT });
  s.addText(desc, { x: x + 0.2, y: 3.75, w: 1.92, h: 1.9, margin: 0, fontFace: BODY, fontSize: 11, color: MUTED });
});
s.addText("Same channels, same limits, same workflows at every stage — nothing gets rebuilt between phases.", {
  x: 0.6, y: 6.25, w: 12.1, h: 0.4, margin: 0, fontFace: BODY, fontSize: 15, italic: true, color: GREEN,
});
pageNum(s, 2);

// ---------------------------------------------------------------- helper for use-case slides
function useCase(n, eb, title, items, imgPath, side, ratio = IMG_RATIO) {
  const sl = pres.addSlide({ masterName: "DARK" });
  eyebrow(sl, eb);
  slideTitle(sl, title);
  if (side === "right") {
    bullets(sl, items, 0.6, 4.55);
    shot(sl, imgPath, 5.35, ratio);
  } else {
    shot(sl, imgPath, 0.6, ratio);
    bullets(sl, items, 8.45, 4.3);
  }
  pageNum(sl, n);
  return sl;
}

// ---------------------------------------------------------------- 3 fleet monitoring
useCase(3, "01 / FLEET MONITORING", "A constellation on one screen", [
  "25 satellites, one live workbook — every asset filters a shared stream by tag. Satellite 26 is a config change, not a new dashboard.",
  "Limits color the board, page Slack, and land as durable events on the asset — nobody has to be watching.",
  "The heater latch-up on GOCE-7 was caught here: green to red in under two minutes.",
], "assets/crop/fleet_status.png", "right");

// ---------------------------------------------------------------- 4 situational awareness
useCase(4, "02 / SITUATIONAL AWARENESS", "Ground tracks, globe, and stations — live", [
  "Live 2D ground tracks and 3D constellation view, driven by the same nav channels your MOC consumes.",
  "Ground-station network drawn on every map — the same stations the commanding procedure uses later.",
  "Nominal is the analysis and process layer on top of your existing stack — not a replacement for it.",
], "assets/crop/earth_view_3d.png", "left");

// ---------------------------------------------------------------- 5 RCA
useCase(5, "03 / ROOT-CAUSE ANALYSIS", "From alert to physics in minutes", [
  "Logs and numeric telemetry side by side — no separate log-aggregator hop during triage.",
  "Derive what isn't telemetered, live: bus power (V × I), then a Stefan–Boltzmann radiator-equilibrium check — proof the spacecraft physically cannot reject the extra heat.",
  "Saved derivations are shared — the next engineer inherits the analysis, not a screenshot.",
], "assets/crop/deepdive_overview.png", "right");

// ---------------------------------------------------------------- 6 TVAC
useCase(6, "04 / TEST ↔ FLIGHT", "Your test campaign never retires", [
  "A March TVAC bench replication overlaid on an August flight anomaly: identical signature — the answer was already in the archive.",
  "Time-independent signature plots (V–I, duty–power) overlay bench and flight with zero timestamp gymnastics.",
  "The same limit checklist executes against live streams and archived runs alike.",
], "assets/crop/tvac_compare.png", "left", TVAC_RATIO);

// ---------------------------------------------------------------- 7 procedures
useCase(7, "05 / PROCEDURES & COMMANDING", "Command it — telemetry closes the loop", [
  "The anomaly-response procedure runs embedded beside live telemetry; every step lands as an event — GO/NO-GO accountability for free.",
  "Completing the transmit step fires a webhook to the ground segment — Nominal drives your qualified commanding stack, it doesn't pretend to be one.",
  "The recovery gate is channel-validated: the spacecraft, not the operator, closes the step.",
], "assets/crop/response_procedure.png", "right");

// ---------------------------------------------------------------- 8 fleet engineering
useCase(8, "06 / FLEET ENGINEERING", "Trend any subsystem across the fleet", [
  "Per-satellite overlays and distributions for every channel — spot the outlier bird at a glance.",
  "Reference-vs-anomaly tables quantify exactly how far off-family a spacecraft is.",
  "The backbone for software-upgrade campaigns: compare behavior before and after, across all birds at once.",
], "assets/crop/eps_heater.png", "left");

// ---------------------------------------------------------------- 9 close
s = pres.addSlide({ masterName: "DARK" });
eyebrow(s, "CLOSE");
s.addText("One platform.\nBench to orbit.", {
  x: 0.6, y: 2.0, w: 5.3, h: 2.0, margin: 0,
  fontFace: HEAD, fontSize: 40, bold: true, color: TEXT,
});
s.addText(
  [
    { text: "Everything shown was created through the public API — whatever we didn't build, you can.", options: { bullet: { code: "2022", indent: 14 }, breakLine: true, paraSpaceAfter: 14 } },
    { text: "Checklists and procedures are versioned like code — limit changes are deliberate, reviewed, published.", options: { bullet: { code: "2022", indent: 14 }, breakLine: true, paraSpaceAfter: 14 } },
    { text: "The asset timeline is the anomaly record: alert → GO → command → ACK → verified recovery.", options: { bullet: { code: "2022", indent: 14 } } },
  ],
  { x: 0.6, y: 4.35, w: 5.1, h: 2.4, margin: 0, fontFace: BODY, fontSize: 14, color: MUTED, valign: "top" }
);
s.addShape("roundRect", { x: 6.24, y: 2.09, w: 6.62, h: 3.75, fill: { color: CARD_EDGE }, rectRadius: 0.06, line: { type: "none" } });
s.addImage({ path: "assets/crop/constellation_overview.png", x: 6.3, y: 2.15, w: 6.5, h: 6.5 / IMG_RATIO });
s.addText("nominal.io", {
  x: 6.3, y: 6.3, w: 6.5, h: 0.35, margin: 0, align: "right",
  fontFace: MONO, fontSize: 12, color: GREEN,
});
pageNum(s, 9);

pres.writeFile({ fileName: "nominal_spacecraft_use_cases.pptx" }).then(() => console.log("deck written"));
