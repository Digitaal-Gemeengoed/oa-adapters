/*
 * De documentkant van de Office Assistent in Collabora Online (proef).
 *
 * oaKit draait niet in de browser maar in het kit-proces van het document:
 * brug.js geeft de functie aan cool.callRemote, dat haar als brontekst naar de
 * kit stuurt en daar in QuickJS uitvoert, met de UNO-API (globaal `uno`).
 * Daarom staat alles in deze ene functie: ze mag niets van buiten gebruiken.
 *
 * Dezelfde logica als oa_document.py en oa_tekst.py van de LibreOffice-
 * extensie (Writer). Eigenschappen via getPropertyValue/setPropertyValue en
 * attributen via getX/setX, met terugval op directe toegang: hoe JS-UNO in
 * Collabora ze aanbiedt, is (nog) niet gedocumenteerd.
 *
 * Antwoord: { ok: true, waarde } of { ok: false, fout, melding }, zodat het
 * niet afhangt van hoe callRemote uitzonderingen doorgeeft.
 */
// eslint-disable-next-line no-unused-vars
function oaKit(opdracht, a) {
  const GENUMMERD = /^(\d+|[a-zA-Z]{1,3}|[ivxlcIVXLC]+)[.)]$|^\d+$/;
  const KOP = /^(?:heading|kop)(\d)$/;
  const STANDAARD = { titel: "Title", onderwerp: "Subject", trefwoorden: "Keywords", auteur: "Author", omschrijving: "Description", taal: "Language" };
  const ALS_EIGEN = { categorie: "Categorie", status: "Status" };

  function Fout(soort, melding) {
    const e = new Error(melding);
    e.oaSoort = soort;
    return e;
  }
  const gewijzigd = (m) => Fout("gewijzigd", m);

  // --- toegang tot UNO -------------------------------------------------------
  function p(obj, naam) {
    if (typeof obj.getPropertyValue === "function") {
      try {
        return obj.getPropertyValue(naam);
      } catch (e) {
        /* geen eigenschap in de set: probeer direct */
      }
    }
    return obj[naam];
  }
  function zet(obj, naam, waarde) {
    if (typeof obj.setPropertyValue === "function") {
      try {
        obj.setPropertyValue(naam, waarde);
        return;
      } catch (e) {
        /* een attribuut (zoals SearchString), geen eigenschap: setX */
      }
    }
    zetAttr(obj, naam, waarde);
  }
  function attr(obj, naam) {
    const g = obj["get" + naam];
    if (typeof g === "function") {
      try {
        return g.call(obj);
      } catch (e) {
        /* geen getter: direct */
      }
    }
    return obj[naam];
  }
  function zetAttr(obj, naam, waarde) {
    const s = obj["set" + naam];
    if (typeof s === "function") s.call(obj, waarde);
    else obj[naam] = waarde;
  }
  function* alle(opsomming) {
    while (opsomming.hasMoreElements()) yield opsomming.nextElement();
  }
  const lijst = (x) => (x == null ? [] : Array.isArray(x) ? x : Array.from(x));
  const schoon = (t) => String(t || "").replace(/[\r\n\u000b]/g, " ").trim();
  const zonderSpaties = (s) => String(s || "").replace(/\s+/g, "").toLowerCase();

  function document_() {
    const desktop = uno.idl.com.sun.star.frame.Desktop.create(uno.componentContext);
    const frame = desktop.getCurrentFrame();
    if (!frame) throw Fout("intern", "Geen document gevonden.");
    return frame.getController().getModel();
  }

  // --- structuur (zoals oa_document.py) ------------------------------------
  const isTitel = (stijl) => ["title", "titel"].includes(zonderSpaties(stijl));
  function niveauUitStijl(stijl, overzicht) {
    const s = zonderSpaties(stijl);
    const m = KOP.exec(s);
    if (m) return Math.min(Number(m[1]), 6);
    if (s === "title" || s === "titel") return 1;
    if (overzicht >= 1 && overzicht <= 6) return overzicht;
    return 0;
  }
  function* onderdelen(doc) {
    let alinea = 0;
    let tabel = 0;
    for (const el of alle(doc.getText().createEnumeration())) {
      if (el.supportsService("com.sun.star.text.Paragraph")) yield ["alinea", alinea++, el];
      else if (el.supportsService("com.sun.star.text.TextTable")) yield ["tabel", tabel++, el];
    }
  }
  const stukken = (alinea) => [...alle(alinea.createEnumeration())];
  function afbeeldingen(alinea) {
    const gevonden = [];
    const gezien = new Set();
    const voegToe = (inhoud) => {
      for (const x of alle(inhoud)) {
        const naam = String(attr(x, "Name"));
        if (x.supportsService("com.sun.star.text.TextGraphicObject") && !gezien.has(naam)) {
          gezien.add(naam);
          gevonden.push(x);
        }
      }
    };
    for (const s of stukken(alinea)) if (p(s, "TextPortionType") === "Frame") voegToe(s.createContentEnumeration("com.sun.star.text.TextContent"));
    voegToe(alinea.createContentEnumeration("com.sun.star.text.TextContent"));
    return gevonden;
  }
  function links(alinea) {
    const uit = [];
    for (const s of stukken(alinea)) {
      if (p(s, "TextPortionType") !== "Text") continue;
      const url = p(s, "HyperLinkURL");
      if (url) {
        const vorige = uit[uit.length - 1];
        if (vorige && vorige.adres === url && vorige.open) {
          vorige.tekst += s.getString();
          vorige.stukken.push(s);
        } else uit.push({ tekst: s.getString(), adres: url, stukken: [s], open: true });
      } else if (uit.length) uit[uit.length - 1].open = false;
    }
    return uit;
  }
  function heel(alinea, eigenschap, test) {
    const s = stukken(alinea).filter((x) => p(x, "TextPortionType") === "Text" && x.getString().trim());
    return s.length > 0 && s.every((x) => test(p(x, eigenschap)));
  }
  const alt = (b) => String(p(b, "Title") || p(b, "Description") || "");

  function leesBlokken(doc) {
    const reeks = [];
    for (const [soort, index, el] of onderdelen(doc)) {
      if (soort === "tabel") {
        const rijen = [];
        const nr = el.getRows().getCount();
        const nk = el.getColumns().getCount();
        for (let r = 0; r < nr; r++) {
          const rij = [];
          for (let k = 0; k < nk; k++) rij.push(String(el.getCellByPosition(k, r).getString()));
          rijen.push(rij);
        }
        const kop = p(el, "RepeatHeadline") ? Number(p(el, "HeaderRowCount")) : 0;
        reeks.push({ soort: "tabel", bron: index, rijen, kopregels: kop });
        continue;
      }
      const tekst = schoon(el.getString());
      const l = links(el);
      const b = afbeeldingen(el);
      const inline = [
        ...l.map((x, i) => ({ soort: "link", tekst: String(x.tekst), href: String(x.adres), index: i })),
        ...b.map((x, i) => ({ soort: "afbeelding", alt: alt(x), index: i })),
      ];
      if (!tekst && !inline.length) continue;
      const stijl = String(p(el, "ParaStyleName") || "");
      const niveau = niveauUitStijl(stijl, Number(p(el, "OutlineLevel") || 0));
      let lijstSoort = null;
      if (niveau === 0 && p(el, "NumberingIsNumber")) lijstSoort = { genummerd: GENUMMERD.test(String(p(el, "ListLabelString") || "").trim()) };
      reeks.push({
        bron: index,
        niveau,
        titel: isTitel(stijl),
        tekst,
        vet: heel(el, "CharWeight", (w) => w >= 150),
        onderstreept: heel(el, "CharUnderline", (u) => u !== 0),
        inline,
        lijst: lijstSoort,
      });
    }
    return reeks;
  }

  function zoek(doc, soort, index) {
    for (const [s, i, el] of onderdelen(doc)) if (s === soort && i === index) return el;
    throw gewijzigd("Dit deel van het document is niet meer gevonden. Beoordeel opnieuw.");
  }
  function alinea(doc, index, verwacht) {
    const el = zoek(doc, "alinea", index);
    if (schoon(el.getString()) !== verwacht) throw gewijzigd("Het document is intussen gewijzigd. Beoordeel opnieuw.");
    return el;
  }

  function voerUit(doc, o) {
    if (o.soort === "niveau") {
      const el = alinea(doc, o.alinea, o.tekst);
      zet(el, "ParaStyleName", o.titel ? "Title" : o.niveau ? "Heading " + o.niveau : "Standard");
    } else if (o.soort === "tabelkop") {
      const t = zoek(doc, "tabel", o.tabel);
      zet(t, "RepeatHeadline", true);
      zet(t, "HeaderRowCount", 1);
      for (const naam of lijst(t.getCellNames())) {
        if (/^[A-Z]+1$/.test(naam)) for (const a2 of alle(t.getCellByName(naam).getText().createEnumeration())) zet(a2, "ParaStyleName", "Table Heading");
      }
    } else if (o.soort === "alt") {
      const beelden = afbeeldingen(alinea(doc, o.alinea, o.tekst));
      if (o.afbeelding >= beelden.length) throw gewijzigd("De afbeelding is niet meer gevonden. Beoordeel opnieuw.");
      zet(beelden[o.afbeelding], "Title", o.alt);
      zet(beelden[o.afbeelding], "Description", o.alt);
    } else if (o.soort === "linktekst") {
      const el = alinea(doc, o.alinea, o.alineatekst);
      const l = links(el);
      if (o.link >= l.length) throw gewijzigd("De link is niet meer gevonden. Beoordeel opnieuw.");
      const { adres, stukken: s } = l[o.link];
      const cursor = doc.getText().createTextCursorByRange(s[0].getStart());
      cursor.gotoRange(s[s.length - 1].getEnd(), true);
      cursor.setString(o.tekst);
      zet(cursor, "HyperLinkURL", adres || o.href || "");
    } else throw Fout("niet-uitvoerbaar", "Onbekende opdracht: " + o.soort);
  }

  function toon(doc, d) {
    const controller = doc.getCurrentController();
    const vc = controller.getViewCursor();
    if (d.soort === "tabel") {
      const t = zoek(doc, "tabel", d.tabel);
      const namen = lijst(t.getCellNames());
      vc.gotoRange(t.getCellByName(namen[0]).getStart(), false);
      vc.gotoRange(t.getCellByName(namen[namen.length - 1]).getEnd(), true);
      return;
    }
    const el = zoek(doc, "alinea", d.alinea);
    if (d.soort === "afbeelding") {
      const b = afbeeldingen(el);
      if (d.afbeelding < b.length) {
        controller.select(b[d.afbeelding]);
        return;
      }
    }
    if (d.soort === "link") {
      const l = links(el);
      if (d.link < l.length) {
        const s = l[d.link].stukken;
        vc.gotoRange(s[0].getStart(), false);
        vc.gotoRange(s[s.length - 1].getEnd(), true);
        return;
      }
    }
    vc.gotoRange(el.getStart(), false);
    vc.gotoRange(el.getEnd(), true);
  }

  // --- eigenschappen ----------------------------------------------------------
  const eigenSet = (doc) => attr(doc.getDocumentProperties(), "UserDefinedProperties");
  function leesEigenschap(doc, naam) {
    const e = eigenSet(doc);
    return e.getPropertySetInfo().hasPropertyByName(naam) ? String(e.getPropertyValue(naam)) : null;
  }
  function schrijfEigenschap(doc, naam, waarde) {
    const e = eigenSet(doc);
    if (e.getPropertySetInfo().hasPropertyByName(naam)) e.setPropertyValue(naam, waarde);
    else e.addProperty(naam, 128, waarde); // 128 = REMOVABLE
  }
  function leesEigenschappen(doc) {
    const dp = doc.getDocumentProperties();
    const standaard = {};
    for (const [naam, veld] of Object.entries(STANDAARD)) {
      let w = attr(dp, veld);
      if (veld === "Keywords") w = lijst(w).filter(Boolean).join(", ");
      else if (veld === "Language") w = w ? [attr(w, "Language"), attr(w, "Country")].filter(Boolean).join("-") : "";
      if (w != null && String(w).trim()) standaard[naam] = String(w).trim();
    }
    const eigen = {};
    const props = attr(dp, "UserDefinedProperties");
    for (const pr of lijst(props.getPropertySetInfo().getProperties())) {
      const naam = String(attr(pr, "Name"));
      if (naam.startsWith("oa-")) continue;
      try {
        eigen[naam] = String(props.getPropertyValue(naam));
      } catch (e) {
        /* overslaan */
      }
    }
    for (const [naam, label] of Object.entries(ALS_EIGEN)) if (eigen[label]) standaard[naam] = eigen[label];
    return { standaard, eigen };
  }
  function schrijfStandaard(doc, naam, waarde) {
    if (ALS_EIGEN[naam]) return schrijfEigenschap(doc, ALS_EIGEN[naam], waarde);
    const veld = STANDAARD[naam];
    if (!veld) return;
    const dp = doc.getDocumentProperties();
    if (veld === "Keywords") zetAttr(dp, veld, String(waarde).split(",").map((x) => x.trim()).filter(Boolean));
    else if (veld === "Language") throw Fout("niet-uitvoerbaar", "De taal van het document zetten kan in deze proef nog niet.");
    else zetAttr(dp, veld, String(waarde));
  }

  // --- tekst vervangen en selectie (zoals oa_tekst.py, Writer) ---------------
  const VOOR = "(?<![\\p{L}\\p{N}_])";
  const NA = "(?![\\p{L}\\p{N}_])";
  const icuPatroon = (van) => VOOR + "\\Q" + van.split("\\E").join("\\E\\\\E\\Q") + "\\E" + NA;
  function icuVervanging(naar) {
    if (naar.includes("\\")) throw Fout("niet-uitvoerbaar", "Een vervangtekst met een backslash kan niet letterlijk worden ingevoegd.");
    return naar.replace(/&/g, "\\&").replace(/\$/g, "\\$");
  }
  function orden(paren) {
    const gezien = new Set();
    const uit = [];
    for (const { van = "", naar = "" } of paren || []) {
      if (!van.trim() || van === naar || gezien.has(van)) continue;
      gezien.add(van);
      uit.push([van, naar]);
    }
    return uit.sort((x, y) => y[0].length - x[0].length);
  }
  function vervangTekst(doc, paren) {
    let aantal = 0;
    for (const [van, naar] of orden(paren)) {
      const d = doc.createReplaceDescriptor();
      zet(d, "SearchString", icuPatroon(van));
      zet(d, "ReplaceString", icuVervanging(naar));
      zet(d, "SearchRegularExpression", true);
      zet(d, "SearchCaseSensitive", true);
      aantal += Number(doc.replaceAll(d));
    }
    return aantal;
  }
  function leesSelectie(doc) {
    const sel = doc.getCurrentController().getSelection();
    if (!sel) return "";
    if (typeof sel.getCount === "function" && sel.supportsService("com.sun.star.text.TextRanges")) {
      const delen = [];
      for (let i = 0; i < sel.getCount(); i++) delen.push(String(sel.getByIndex(i).getString()));
      return delen.join("\n");
    }
    return typeof sel.getString === "function" ? String(sel.getString()) : "";
  }

  function soortVan(doc) {
    if (doc.supportsService("com.sun.star.sheet.SpreadsheetDocument")) return "rekenblad";
    if (doc.supportsService("com.sun.star.presentation.PresentationDocument")) return "presentatie";
    if (doc.supportsService("com.sun.star.text.TextDocument")) return "tekst";
    return "onbekend";
  }
  function naamVan(doc) {
    try {
      const t = attr(doc.getDocumentProperties(), "Title");
      if (t) return String(t);
    } catch (e) {
      /* terugval */
    }
    try {
      const url = String(doc.getURL() || "");
      if (url) return decodeURIComponent(url.split("/").pop());
    } catch (e) {
      /* terugval */
    }
    return "Naamloos document";
  }

  try {
    const doc = document_();
    let waarde;
    switch (opdracht) {
      case "status":
        waarde = { naam: naamVan(doc), soort: soortVan(doc) };
        break;
      case "blokken":
        waarde = leesBlokken(doc);
        break;
      case "opdracht":
        voerUit(doc, a);
        break;
      case "toon":
        toon(doc, a);
        break;
      case "eigenschap":
        waarde = leesEigenschap(doc, a.naam);
        break;
      case "schrijf-eigenschap":
        schrijfEigenschap(doc, a.naam, a.waarde);
        break;
      case "eigenschappen":
        waarde = leesEigenschappen(doc);
        break;
      case "standaardeigenschap":
        schrijfStandaard(doc, a.naam, a.waarde);
        break;
      case "tekst-vervangen":
        waarde = vervangTekst(doc, a.paren);
        break;
      case "selectie":
        waarde = leesSelectie(doc);
        break;
      default:
        throw Fout("niet-uitvoerbaar", "Onbekende vraag: " + opdracht);
    }
    return { ok: true, waarde: waarde === undefined ? null : waarde };
  } catch (e) {
    return { ok: false, fout: (e && e.oaSoort) || "intern", melding: String((e && e.message) || e) };
  }
}
