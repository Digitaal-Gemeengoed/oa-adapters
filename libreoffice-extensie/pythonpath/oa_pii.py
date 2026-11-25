# -*- coding: utf-8 -*-
"""Anonimiseren in het document, voor Writer (zoals de MIRA-demo).

Elke plaatshouder ([PERSOON 1]) staat in de tekst met een bladwijzer
eromheen. De naam van de bladwijzer draagt de plek, de plaatshouder en of
het nog een voorvertoning is:

    oa-pii p12 [PERSOON 1] v      (voorvertoning)
    oa-pii p12 [PERSOON 1]        (bevestigd)

De tekst krijgt de kleur van het niveau (art. 6 groen, art. 9 oranje,
art. 10 rood); een voorvertoning heeft een gestippelde rand. Terugzetten:
de bladwijzer weg, de tekst terug, de opmaak terug naar die van de alinea.

Opmerkingen (annotaties) kunnen geen bladwijzers bevatten. Daar staat de
plaatshouder als gewone tekst, en de plekken staan in de documenteigenschap
"oa-pii-opmerkingen": plek, plaatshouder, voorvertoning en welke opmerking.
Nooit de originele waarde: die staat alleen (versleuteld) in het register.

Klikt de medewerker in een plaatshouder, dan onthoudt de selectieluisteraar
welke; het paneel vraagt dat regelmatig op (/pii-klik). Het rechtermuismenu
krijgt "Anonimiseer selectie (Assistent)".
"""
import functools
import json
import re
import urllib.parse

import uno
import unohelper
from com.sun.star.document import XDocumentEventListener
from com.sun.star.frame import FeatureStateEvent, XDispatch, XDispatchProviderInterceptor
from com.sun.star.ui import XContextMenuInterceptor
from com.sun.star.ui.ContextMenuInterceptorAction import EXECUTE_MODIFIED, IGNORED
from com.sun.star.view import XSelectionChangeListener

from oa_tekst import icu_patroon

VOORVOEGSEL = "oa-pii "
NAAM = re.compile(r"^oa-pii (p\d+) (\[[^\]]+\])( v)?$")
ACHTERGROND = {1: 0xE3F1E6, 2: 0xFDF0D8, 3: 0xFBE3E3}
KLEUR = {1: 0x1E6B33, 2: 0x8A5300, 3: 0xA4001D}
OPMAAK = ("CharBackColor", "CharColor", "CharLeftBorder", "CharRightBorder", "CharTopBorder", "CharBottomBorder")
OPDRACHT = "service:nl.digitaalgemeengoed.oa.Assistent?module:anon-selectie"


def _lijn(kleur, gestippeld):
    l = uno.createUnoStruct("com.sun.star.table.BorderLine2")
    if gestippeld:
        l.Color = kleur
        l.LineWidth = 18
        l.LineStyle = 2  # DASHED
        l.OuterLineWidth = 18
    return l


def _kleur(rng, ppl, voorvertoning):
    rng.CharBackColor = ACHTERGROND.get(ppl, ACHTERGROND[1])
    rng.CharColor = KLEUR.get(ppl, KLEUR[1])
    for kant in ("CharLeftBorder", "CharRightBorder", "CharTopBorder", "CharBottomBorder"):
        setattr(rng, kant, _lijn(KLEUR.get(ppl, KLEUR[1]), voorvertoning))


def _wis_opmaak(rng):
    try:
        rng.setPropertiesToDefault(OPMAAK)
    except Exception:
        for naam in OPMAAK:
            try:
                rng.setPropertyToDefault(naam)
            except Exception:
                pass


def _naam(naam):
    """De naam van een bladwijzer zoals wij hem schrijven. In een .docx bewaart LibreOffice
    "oa-pii p2 [PERSOON 11]" als "oa-pii_p2_%5BPERSOON_11%5D" (Word staat alleen letters,
    cijfers en _ toe); bij het openen komt die vorm terug."""
    if naam.startswith("oa-pii_"):
        return urllib.parse.unquote(naam).replace("_", " ")
    return naam


def _bladwijzers(document):
    bw = document.getBookmarks()
    uit = []
    for naam in bw.getElementNames():
        m = NAAM.match(_naam(naam))
        if m:
            uit.append((m, bw.getByName(naam)))
    return uit


def _plek_nummer(m):
    return int(m.group(1)[1:])


def _volgorde(a, b):
    """Volgorde in het document; tussen verschillende teksten (tabel, kop) op nummer."""
    ra, rb = a[1].getAnchor(), b[1].getAnchor()
    try:
        if ra.getText() == rb.getText():
            c = ra.getText().compareRegionStarts(ra, rb)
            if c:
                return -c
    except Exception:
        pass
    return _plek_nummer(a[0]) - _plek_nummer(b[0])


def lees_plekken(document):
    gesorteerd = sorted(_bladwijzers(document), key=functools.cmp_to_key(_volgorde))
    uit = [{"plek": m.group(1), "plaatshouder": m.group(2), "voorvertoning": bool(m.group(3))} for m, _ in gesorteerd]
    # Daarna de opmerkingen (ze staan naast de tekst).
    uit += [{"plek": x["plek"], "plaatshouder": x["plaatshouder"], "voorvertoning": bool(x.get("v"))} for x in _opm_plekken(document)]
    return uit


# ---------------------------------------------------------------------------
# Opmerkingen
# ---------------------------------------------------------------------------

OPM_EIGENSCHAP = "oa-pii-opmerkingen"


def _opmerkingen(document):
    """De opmerkingen in het document; elke opmerking krijgt zo nodig een naam om haar terug te vinden."""
    uit = []
    try:
        velden = document.getTextFields().createEnumeration()
    except Exception:
        return uit
    n = 0
    while velden.hasMoreElements():
        v = velden.nextElement()
        if not v.supportsService("com.sun.star.text.textfield.Annotation"):
            continue
        n += 1
        if not v.Name:
            try:
                v.Name = "oa-opmerking-%d" % n
            except Exception:
                pass
        uit.append(v)
    return uit


def _opm_plekken(document):
    from oa_document import lees_eigenschap
    try:
        return json.loads(lees_eigenschap(document, OPM_EIGENSCHAP) or "[]")
    except Exception:
        return []


def _bewaar_opm_plekken(document, plekken):
    from oa_document import schrijf_eigenschap
    schrijf_eigenschap(document, OPM_EIGENSCHAP, json.dumps(plekken, ensure_ascii=False))


def _markeer_in_opmerkingen(document, van, plaatshouder, voorvertoning, volg, nieuw):
    patroon = re.compile(r"(?<!\w)" + re.escape(van) + r"(?!\w)")
    plekken = _opm_plekken(document)
    for opm in _opmerkingen(document):
        tekst = opm.Content or ""
        treffers = list(patroon.finditer(tekst))
        if not treffers:
            continue
        for t in reversed(treffers):
            tekst = tekst[: t.start()] + plaatshouder + tekst[t.end():]
        opm.Content = tekst
        for _t in treffers:
            volg += 1
            plek = "p%d" % volg
            plekken.append({"plek": plek, "plaatshouder": plaatshouder, "v": bool(voorvertoning), "opm": opm.Name})
            nieuw.append({"plek": plek, "plaatshouder": plaatshouder, "voorvertoning": bool(voorvertoning)})
    _bewaar_opm_plekken(document, plekken)
    return volg


def _herstel_in_opmerking(document, p):
    plekken = _opm_plekken(document)
    rec = next((x for x in plekken if x["plek"] == p["plek"]), None)
    if rec is None:
        return False
    opm = next((o for o in _opmerkingen(document) if o.Name == rec["opm"]), None)
    if opm is not None:
        tekst = opm.Content or ""
        i = tekst.find(rec["plaatshouder"])
        if i >= 0:
            opm.Content = tekst[:i] + p["waarde"] + tekst[i + len(rec["plaatshouder"]):]
    _bewaar_opm_plekken(document, [x for x in plekken if x["plek"] != p["plek"]])
    return True


def markeer(document, markeringen):
    """Vervangt elke waarde (als heel woord, de langste eerst) door een gemarkeerde plaatshouder,
    in de tekst en in de opmerkingen."""
    volg = max([_plek_nummer(m) for m, _ in _bladwijzers(document)] + [int(x["plek"][1:]) for x in _opm_plekken(document)] + [0])
    nieuw = []
    gezien = set()
    for mk in sorted(markeringen, key=lambda x: -len(x.get("van", ""))):
        van = mk.get("van", "")
        if not van.strip() or van in gezien:
            continue
        gezien.add(van)
        d = document.createSearchDescriptor()
        d.SearchString = icu_patroon(van)
        d.SearchRegularExpression = True
        d.SearchCaseSensitive = True
        gevonden = document.findAll(d)
        for i in range(gevonden.getCount()):
            rng = gevonden.getByIndex(i)
            if _in_plaatshouder(document, rng):
                continue
            volg += 1
            plek = "p%d" % volg
            tekst = rng.getText()
            cursor = tekst.createTextCursorByRange(rng)
            cursor.setString(mk["plaatshouder"])
            _kleur(cursor, int(mk.get("ppl", 1)), bool(mk.get("voorvertoning")))
            bw = document.createInstance("com.sun.star.text.Bookmark")
            bw.setName("%s%s %s%s" % (VOORVOEGSEL, plek, mk["plaatshouder"], " v" if mk.get("voorvertoning") else ""))
            tekst.insertTextContent(cursor, bw, True)
            nieuw.append({"plek": plek, "plaatshouder": mk["plaatshouder"], "voorvertoning": bool(mk.get("voorvertoning"))})
        volg = _markeer_in_opmerkingen(document, van, mk["plaatshouder"], mk.get("voorvertoning"), volg, nieuw)
    return nieuw


def herkleur(document, plaatshouder, ppl):
    """Andere grondslag: de plekken van deze plaatshouder krijgen de kleur van het nieuwe niveau.
    In opmerkingen staat platte tekst; daar is niets te kleuren."""
    for m, bw in _bladwijzers(document):
        if m.group(2) == plaatshouder:
            a = bw.getAnchor()
            _kleur(a.getText().createTextCursorByRange(a), int(ppl), bool(m.group(3)))


def _in_plaatshouder(document, rng):
    for _m, bw in _bladwijzers(document):
        a = bw.getAnchor()
        try:
            t = a.getText()
            if t == rng.getText() and t.compareRegionStarts(a, rng) >= 0 and t.compareRegionEnds(rng, a) >= 0:
                return True
        except Exception:
            continue
    return False


def _zoek(document, plek):
    for m, bw in _bladwijzers(document):
        if m.group(1) == plek:
            return m, bw
    return None, None


def herstel(document, plekken):
    for p in plekken:
        _m, bw = _zoek(document, p["plek"])
        if bw is None:
            _herstel_in_opmerking(document, p)
            continue
        a = bw.getAnchor()
        cursor = a.getText().createTextCursorByRange(a)
        cursor.setString(p["waarde"])
        _wis_opmaak(cursor)
        a.getText().removeTextContent(bw)


def zet_definitief(document):
    opm = _opm_plekken(document)
    if any(x.get("v") for x in opm):
        _bewaar_opm_plekken(document, [{**x, "v": False} for x in opm])
    for m, bw in _bladwijzers(document):
        if not m.group(3):
            continue
        bw.setName("%s%s %s" % (VOORVOEGSEL, m.group(1), m.group(2)))
        a = bw.getAnchor()
        for kant in ("CharLeftBorder", "CharRightBorder", "CharTopBorder", "CharBottomBorder"):
            setattr(a, kant, _lijn(0, False))


def toon(document, plek):
    _m, bw = _zoek(document, plek)
    if bw is not None:
        document.getCurrentController().select(bw.getAnchor())
        return
    # In een opmerking: de plek waar de opmerking aan hangt.
    rec = next((x for x in _opm_plekken(document) if x["plek"] == plek), None)
    opm = next((o for o in _opmerkingen(document) if rec and o.Name == rec["opm"]), None)
    if opm is not None:
        document.getCurrentController().select(opm.getAnchor())


def plek_bij_cursor(document):
    """De plaatshouder waarin de cursor staat, of None."""
    vc = document.getCurrentController().getViewCursor()
    ingeklapt = vc.isCollapsed()
    for m, bw in _bladwijzers(document):
        a = bw.getAnchor()
        try:
            t = a.getText()
            if t != vc.getText():
                continue
            begin, eind = t.compareRegionStarts(a, vc), t.compareRegionEnds(vc, a)
            # Een cursor zonder selectie telt alleen echt binnenin: ernaast typen is geen klik.
            if (ingeklapt and begin > 0 and eind > 0) or (not ingeklapt and begin >= 0 and eind >= 0):
                return {"plek": m.group(1), "plaatshouder": m.group(2), "voorvertoning": bool(m.group(3))}
        except Exception:
            continue
    return None


class Klikken(unohelper.Base, XSelectionChangeListener, XContextMenuInterceptor):
    """Luistert naar de selectie (klik in een plaatshouder) en vult het rechtermuismenu aan."""

    def __init__(self, document):
        from oa_bladen import soort_van
        self.document = document
        self.tekst = soort_van(document) == "tekst"
        self.laatste = None
        self.teller = 0
        c = document.getCurrentController()
        c.addSelectionChangeListener(self)
        try:
            c.registerContextMenuInterceptor(self)
        except Exception:
            pass

    # XSelectionChangeListener
    def selectionChanged(self, _ev):
        try:
            p = plek_bij_cursor(self.document) if self.tekst else plek_bij_selectie(self.document)
        except Exception:
            p = None
        plek = p["plek"] if p else None
        if plek and plek != (self.laatste or {}).get("plek"):
            self.teller += 1
            self.laatste = p
        elif not plek:
            self.laatste = None

    def disposing(self, _ev):
        pass

    # XContextMenuInterceptor
    def notifyContextMenuExecute(self, ev):
        try:
            from oa_tekst import lees_selectie
            # Niet via het klembord: dit gebeurt bij elke klik met rechts.
            tekst = lees_selectie(self.document, klembord=False)
            if not tekst.strip():
                return IGNORED
            menu = ev.ActionTriggerContainer
            scheiding = menu.createInstance("com.sun.star.ui.ActionTriggerSeparator")
            item = menu.createInstance("com.sun.star.ui.ActionTrigger")
            item.setPropertyValue("Text", "Anonimiseer selectie (Assistent)")
            item.setPropertyValue("CommandURL", OPDRACHT)
            menu.insertByIndex(0, item)
            menu.insertByIndex(1, scheiding)
            return EXECUTE_MODIFIED
        except Exception:
            return IGNORED

    def stand(self):
        return {"n": self.teller, **(self.laatste or {})}


# ---------------------------------------------------------------------------
# Calc en Impress. Daar zijn geen bladwijzers: een plaatshouder is de tekst
# [SOORT n] zelf, in een cel of tekstvak. De plek is het vak plus het hoeveelste
# voorkomen erin (s0c2r5#0, d1s3#0). Of het nog een voorvertoning is, weet het
# register; in het document is dat een gestippelde onderstreping.
# ---------------------------------------------------------------------------

PLAATSHOUDER = re.compile(r"\[[A-Z][A-Z-]* \d+\]")
STIPPEL = 5  # com.sun.star.awt.FontUnderline.DASH


def _vakken(document):
    """(kenmerk, vak met tekst) voor elke cel met tekst of elk tekstvak."""
    from oa_bladen import soort_van
    if soort_van(document) == "rekenblad":
        from com.sun.star.sheet.CellFlags import STRING
        bladen = document.getSheets()
        for i in range(bladen.getCount()):
            reeksen = bladen.getByIndex(i).queryContentCells(STRING)
            cellen = reeksen.getCells().createEnumeration()
            gevonden = []
            while cellen.hasMoreElements():
                cel = cellen.nextElement()
                a = cel.getCellAddress()
                gevonden.append(((a.Row, a.Column), "s%dc%dr%d" % (a.Sheet, a.Column, a.Row), cel))
            for _k, kenmerk, cel in sorted(gevonden, key=lambda x: x[0]):
                yield kenmerk, cel
    else:
        from oa_tekst import _tekstvakken
        paginas = document.getDrawPages()
        for i in range(paginas.getCount()):
            for j, vak in enumerate(_tekstvakken(paginas.getByIndex(i))):
                yield "d%ds%d" % (i, j), vak


def _vak(document, kenmerk):
    for k, v in _vakken(document):
        if k == kenmerk:
            return v
    return None


def _cursor(vak, begin, lengte):
    c = vak.createTextCursor()
    c.gotoStart(False)
    c.goRight(begin, False)
    c.goRight(lengte, True)
    return c


def lees_plekken_bladen(document):
    uit = []
    for kenmerk, vak in _vakken(document):
        for i, m in enumerate(PLAATSHOUDER.finditer(vak.getString())):
            uit.append({"plek": "%s#%d" % (kenmerk, i), "plaatshouder": m.group(0), "voorvertoning": False})
    return uit


def markeer_bladen(document, markeringen):
    voor = {p["plek"] for p in lees_plekken_bladen(document)}
    geordend = sorted([m for m in markeringen if m.get("van", "").strip()], key=lambda x: -len(x["van"]))
    for _kenmerk, vak in _vakken(document):
        tekst = vak.getString()
        bezet = [m.span() for m in PLAATSHOUDER.finditer(tekst)]
        nieuw = []
        for mk in geordend:
            for m in re.finditer(r"(?<!\w)" + re.escape(mk["van"]) + r"(?!\w)", tekst):
                b, e = m.span()
                if not any(b < x[1] and e > x[0] for x in bezet):
                    bezet.append((b, e))
                    nieuw.append((b, e, mk))
        for b, e, mk in sorted(nieuw, key=lambda x: -x[0]):
            c = _cursor(vak, b, e - b)
            c.setString(mk["plaatshouder"])
            c.CharColor = KLEUR.get(int(mk.get("ppl", 1)), KLEUR[1])
            c.CharUnderline = STIPPEL if mk.get("voorvertoning") else 0
    _markeer_getallen(document, geordend)
    return [p for p in lees_plekken_bladen(document) if p["plek"] not in voor]


def _markeer_getallen(document, geordend):
    """Een cel met een getal of datum (geen formule) die precies een gevonden waarde toont,
    zoals een geboortedatum: de cel wordt tekst met de plaatshouder."""
    from oa_bladen import soort_van
    if soort_van(document) != "rekenblad":
        return
    from com.sun.star.sheet.CellFlags import VALUE, DATETIME
    van = {}
    for mk in geordend:
        van.setdefault(mk["van"].strip(), mk)
    bladen = document.getSheets()
    for i in range(bladen.getCount()):
        reeksen = bladen.getByIndex(i).queryContentCells(VALUE | DATETIME)
        cellen = reeksen.getCells().createEnumeration()
        while cellen.hasMoreElements():
            cel = cellen.nextElement()
            mk = van.get(cel.getString().strip())
            if mk is None:
                continue
            cel.setString(mk["plaatshouder"])
            c = _cursor(cel, 0, len(mk["plaatshouder"]))
            c.CharColor = KLEUR.get(int(mk.get("ppl", 1)), KLEUR[1])
            c.CharUnderline = STIPPEL if mk.get("voorvertoning") else 0


def _splits(plek):
    kenmerk, _, n = plek.rpartition("#")
    return kenmerk, int(n or 0)


def herstel_bladen(document, plekken):
    # Per vak van achter naar voren, zodat de nummering van de andere plekken klopt.
    for p in sorted(plekken, key=lambda x: (_splits(x["plek"])[0], -_splits(x["plek"])[1])):
        kenmerk, n = _splits(p["plek"])
        vak = _vak(document, kenmerk)
        if vak is None:
            continue
        treffers = list(PLAATSHOUDER.finditer(vak.getString()))
        if n >= len(treffers):
            continue
        b, e = treffers[n].span()
        c = _cursor(vak, b, e - b)
        c.setString(p["waarde"])
        for naam in ("CharColor", "CharUnderline"):
            try:
                c.setPropertyToDefault(naam)
            except Exception:
                pass


def herkleur_bladen(document, plaatshouder, ppl):
    for _kenmerk, vak in _vakken(document):
        for m in PLAATSHOUDER.finditer(vak.getString()):
            if m.group(0) == plaatshouder:
                b, e = m.span()
                _cursor(vak, b, e - b).CharColor = KLEUR.get(int(ppl), KLEUR[1])


def zet_definitief_bladen(document):
    for _kenmerk, vak in _vakken(document):
        for m in PLAATSHOUDER.finditer(vak.getString()):
            b, e = m.span()
            _cursor(vak, b, e - b).CharUnderline = 0


def toon_bladen(document, plek):
    from oa_bladen import soort_van
    vak = _vak(document, _splits(plek)[0])
    if vak is None:
        return
    c = document.getCurrentController()
    if soort_van(document) == "presentatie":
        kenmerk = _splits(plek)[0]
        c.setCurrentPage(document.getDrawPages().getByIndex(int(kenmerk[1:kenmerk.index("s")])))
    c.select(vak)


def plek_bij_selectie(document):
    """De eerste plaatshouder in de geselecteerde cel of het geselecteerde tekstvak."""
    sel = document.getCurrentController().getSelection()
    if sel is None:
        return None
    kandidaten = []
    if hasattr(sel, "getCellAddress"):
        kandidaten = [sel]
    elif hasattr(sel, "getCount") and hasattr(sel, "getByIndex") and not hasattr(sel, "getRangeAddress"):
        kandidaten = [sel.getByIndex(i) for i in range(sel.getCount())]
    for kenmerk, vak in _vakken(document):
        for k in kandidaten:
            try:
                zelfde = (k == vak) or (hasattr(k, "getCellAddress") and hasattr(vak, "getCellAddress")
                                         and (k.getCellAddress().Sheet, k.getCellAddress().Column, k.getCellAddress().Row)
                                         == (vak.getCellAddress().Sheet, vak.getCellAddress().Column, vak.getCellAddress().Row))
            except Exception:
                zelfde = False
            if zelfde:
                m = PLAATSHOUDER.search(vak.getString())
                if m:
                    return {"plek": "%s#0" % kenmerk, "plaatshouder": m.group(0), "voorvertoning": False}
    return None


# ---------------------------------------------------------------------------
# Inzage: de originele waarden tijdelijk in de tekst (Writer)
# ---------------------------------------------------------------------------
#
# Wie het niveau heeft, kan de originelen in de tekst zien in plaats van de
# plaatshouders. Het document mag dan niet met originelen worden bewaard:
#  - alleen een opgeslagen, ongewijzigd document;
#  - eerst alleen-lezen (.uno:EditDoc): typen kan niet meer, de API wel;
#  - de tekst binnen elke bladwijzer om (de bladwijzer blijft), onderstippeld;
#  - het document kan niet "gewijzigd" worden (disableSetModified): geen vraag
#    om op te slaan bij sluiten, en het automatisch herstel slaat niets op;
#  - opslaan, exporteren, afdrukken, mailen en terug naar bewerken
#    onderschept (en grijs in menu's en werkbalken);
#  - het omwisselen komt niet in Ongedaan maken;
#  - vangnet: bij een opslaggebeurtenis toch eerst de plaatshouders terug.
# Opmerkingen (annotaties) blijven plaatshouders: daar is geen bladwijzer.

GEBLOKKEERD = (".uno:Save", ".uno:Export", ".uno:Print", ".uno:SendMail", ".uno:EditDoc", ".uno:SendViaBluetooth",
               ".uno:SaveACopy", ".uno:SaveAll", ".uno:Signature", ".uno:CheckIn", ".uno:Reload")
ONDERSTIPPELD = 3  # FontUnderline.DOTTED


def _geblokkeerd(url):
    cmd = url.Complete.split("?", 1)[0]
    return cmd.startswith(GEBLOKKEERD)


class _Weiger(unohelper.Base, XDispatch):
    """Doet niets en meldt zich als uitgeschakeld (grijs in menu en werkbalk)."""

    def dispatch(self, url, args):
        pass

    def addStatusListener(self, luisteraar, url):
        e = FeatureStateEvent()
        e.FeatureURL = url
        e.IsEnabled = False
        e.Source = self
        try:
            luisteraar.statusChanged(e)
        except Exception:
            pass

    def removeStatusListener(self, luisteraar, url):
        pass


class _Onderschep(unohelper.Base, XDispatchProviderInterceptor):
    def __init__(self):
        self.slaaf = None
        self.meester = None
        self.weiger = _Weiger()

    def queryDispatch(self, url, doel, vlaggen):
        if _geblokkeerd(url):
            return self.weiger
        return self.slaaf.queryDispatch(url, doel, vlaggen) if self.slaaf else None

    def queryDispatches(self, vragen):
        return tuple(self.queryDispatch(v.FeatureURL, v.FrameName, v.SearchFlags) for v in vragen)

    def getSlaveDispatchProvider(self):
        return self.slaaf

    def setSlaveDispatchProvider(self, x):
        self.slaaf = x

    def getMasterDispatchProvider(self):
        return self.meester

    def setMasterDispatchProvider(self, x):
        self.meester = x


class Inzage(unohelper.Base, XDocumentEventListener):
    def __init__(self, ctx, document):
        self.ctx = ctx
        self.document = document
        self.getoond = {}  # plek -> plaatshouder
        self.waarden = {}  # plek -> origineel (alleen in het geheugen, zolang getoond)
        self.opgeschort = False
        self.onderschep = None
        self.frame = None
        self.alleen_lezen_gezet = False

    @property
    def actief(self):
        return bool(self.getoond)

    def _dispatch(self, cmd):
        helper = self.ctx.ServiceManager.createInstanceWithContext("com.sun.star.frame.DispatchHelper", self.ctx)
        helper.executeDispatch(self.frame, cmd, "", 0, ())

    def _zonder_ongedaan(self, werk):
        um = None
        try:
            um = self.document.getUndoManager()
            um.lock()
        except Exception:
            um = None
        try:
            werk()
        finally:
            if um is not None:
                try:
                    um.unlock()
                except Exception:
                    pass

    def toon(self, waarden):
        """waarden: [{plaatshouder, waarde}]. Geeft het aantal plekken in de tekst."""
        from oa_kern import NietUitvoerbaar
        if self.actief:
            self.verberg()
        doc = self.document
        if not doc.hasLocation():
            raise NietUitvoerbaar("Sla het document eerst op; daarna kun je de originelen in de tekst tonen.")
        if doc.isModified():
            raise NietUitvoerbaar("Het document heeft wijzigingen die nog niet zijn opgeslagen. Sla eerst op; daarna kun je de originelen in de tekst tonen.")
        per = {w["plaatshouder"]: w["waarde"] for w in waarden if w.get("plaatshouder") and w.get("waarde") is not None}
        plekken = [(m, bw) for m, bw in _bladwijzers(doc) if m.group(2) in per]
        if not plekken:
            return 0
        self.frame = doc.getCurrentController().getFrame()
        if not doc.isReadonly():
            self._dispatch(".uno:EditDoc")
            self.alleen_lezen_gezet = True
        if not doc.isReadonly():
            raise NietUitvoerbaar("Het document kon niet op alleen-lezen. De originelen blijven verborgen.")
        self.onderschep = _Onderschep()
        self.frame.registerDispatchProviderInterceptor(self.onderschep)
        doc.disableSetModified()

        for m, _bw in plekken:
            self.getoond[m.group(1)] = m.group(2)
            self.waarden[m.group(1)] = per[m.group(2)]
        self._zonder_ongedaan(self._wissel)
        try:
            doc.addDocumentEventListener(self)
        except Exception:
            pass
        try:
            self.frame.contextChanged()
        except Exception:
            pass
        return len(self.getoond)

    def _wissel(self):
        for plek, waarde in self.waarden.items():
            _m, bw = _zoek(self.document, plek)
            if bw is None:
                continue
            a = bw.getAnchor()
            c = a.getText().createTextCursorByRange(a)
            c.setString(waarde)
            c.CharUnderline = ONDERSTIPPELD

    def _terug(self):
        for plek, plaatshouder in self.getoond.items():
            _m, bw = _zoek(self.document, plek)
            if bw is None:
                continue
            a = bw.getAnchor()
            c = a.getText().createTextCursorByRange(a)
            c.setString(plaatshouder)
            try:
                c.setPropertyToDefault("CharUnderline")
            except Exception:
                c.CharUnderline = 0

    def _zet_terug(self):
        self._zonder_ongedaan(self._terug)
        self.getoond = {}
        self.waarden = {}

    def verberg(self):
        if not self.getoond and self.onderschep is None:
            return
        doc = self.document
        if self.opgeschort:
            self.getoond, self.waarden, self.opgeschort = {}, {}, False
        self._zet_terug()
        try:
            doc.removeDocumentEventListener(self)
        except Exception:
            pass
        if self.onderschep is not None:
            try:
                self.frame.releaseDispatchProviderInterceptor(self.onderschep)
            except Exception:
                pass
            self.onderschep = None
        try:
            doc.enableSetModified()
        except Exception:
            pass
        if self.alleen_lezen_gezet:
            try:
                self._dispatch(".uno:EditDoc")
            except Exception:
                pass
            self.alleen_lezen_gezet = False
        try:
            doc.setModified(False)
        except Exception:
            pass
        try:
            self.frame.contextChanged()
        except Exception:
            pass

    # Vangnet: wordt er toch opgeslagen of gekopieerd (ook via de API, die
    # .uno:Save omzeilt), dan gaan eerst de plaatshouders terug, en daarna weer
    # de originelen. In een bestand komt zo nooit een origineel.
    VOOR = ("OnSave", "OnSaveAs", "OnCopyTo")
    NA = ("OnSaveDone", "OnSaveFailed", "OnSaveAsDone", "OnSaveAsFailed", "OnCopyToDone", "OnCopyToFailed")

    def documentEventOccured(self, e):
        if not self.getoond:
            return
        if e.EventName in self.VOOR and not self.opgeschort:
            self._zonder_ongedaan(self._terug)
            self.opgeschort = True
        elif e.EventName in self.NA and self.opgeschort:
            self._zonder_ongedaan(self._wissel)
            self.opgeschort = False

    def disposing(self, e):
        pass
