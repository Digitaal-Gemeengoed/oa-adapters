# -*- coding: utf-8 -*-
"""Test kit.js (de documentkant in Collabora) tegen een echte LibreOffice.

Collabora voert kit.js uit in QuickJS met JS-UNO. Hier draait kit.js ook in
QuickJS (pip: quickjs), met een `uno`-object dat elke aanroep via JSON aan
PyUNO doorgeeft. Zo toetsen we de logica tegen dezelfde LibreOffice als de
Python-extensie, en vergelijken we met oa_document.py. Wat dit niet toetst:
hoe JS-UNO in Collabora zelf waarden en eigenschappen aanbiedt.

Start eerst: soffice --headless --accept="socket,host=127.0.0.1,port=2002;urp;"
Draai met de Python van LibreOffice (python3.12 op Ubuntu 24.04):
    python3.12 -m pytest collabora-extensie/test
"""
import json, os, sys, unittest

import quickjs

hier = os.path.dirname(__file__)
ext = os.path.join(hier, "..", "..", "libreoffice-extensie")
sys.path[:0] = [os.path.join(ext, "pythonpath"), os.path.join(ext, "test")]
from test_document import verbind, maak_document  # noqa: E402
import oa_document as od  # noqa: E402

KIT = open(os.path.join(hier, "..", "pakket", "kit.js"), encoding="utf-8").read()

SHIM = r"""
function oaWikkel(v) {
  if (v && typeof v === "object" && !Array.isArray(v) && v.__h !== undefined) return oaProxy(v.__h);
  if (Array.isArray(v)) return v.map(oaWikkel);
  if (v && typeof v === "object") { const o = {}; for (const k in v) o[k] = oaWikkel(v[k]); return o; }
  return v;
}
function oaKaal(v) {
  if (v && typeof v === "object" && v.__isProxy) return { __h: v.__h };
  if (Array.isArray(v)) return v.map(oaKaal);
  return v;
}
function oaProxy(h) {
  return new Proxy({}, {
    get(_t, naam) {
      if (naam === "__h") return h;
      if (naam === "__isProxy") return true;
      if (typeof naam !== "string" || naam === "then" || naam === "toJSON") return undefined;
      const r = JSON.parse(__uno(JSON.stringify({ h, vraag: "heeft", naam })));
      if (r.soort === "methode") return function (...args) {
        const a = JSON.parse(__uno(JSON.stringify({ h, vraag: "roep", naam, args: args.map(oaKaal) })));
        if (a.fout) throw new Error(a.fout);
        return oaWikkel(a.w);
      };
      if (r.soort === "waarde") return oaWikkel(r.w);
      return undefined;
    },
    set(_t, naam, w) {
      const a = JSON.parse(__uno(JSON.stringify({ h, vraag: "zet", naam, w: oaKaal(w) })));
      if (a.fout) throw new Error(a.fout);
      return true;
    },
  });
}
var uno = {
  componentContext: oaProxy(0),
  idl: { com: { sun: { star: { frame: { Desktop: { create: () => oaProxy(1) } } } } } },
};
"""


class Desktop:
    """Staat in voor de Desktop: het huidige frame is dat van het testdocument."""

    def __init__(self, doc):
        self.doc = doc

    def getCurrentFrame(self):
        return self.doc.getCurrentController().getFrame()


class Brug:
    def __init__(self, ctx, doc):
        self.objecten = {0: ctx, 1: Desktop(doc)}

    def _handvat(self, o):
        for k, v in self.objecten.items():
            if v is o:
                return k
        k = len(self.objecten)
        self.objecten[k] = o
        return k

    def naar_js(self, v):
        import uno
        if v is None or isinstance(v, (bool, int, float, str)):
            return v
        if isinstance(v, (tuple, list)):
            return [self.naar_js(x) for x in v]
        if isinstance(v, uno.Enum):
            return v.value
        if isinstance(v, uno.ByteSequence):
            return None
        if hasattr(v, "typeName") and not hasattr(v, "queryInterface"):  # struct
            return {"__h": self._handvat(v)}
        return {"__h": self._handvat(v)}

    def naar_py(self, v):
        if isinstance(v, dict) and "__h" in v:
            return self.objecten[v["__h"]]
        if isinstance(v, list):
            return tuple(self.naar_py(x) for x in v)
        return v

    def __call__(self, verzoek):
        v = json.loads(verzoek)
        o = self.objecten[v["h"]]
        try:
            if v["vraag"] == "heeft":
                try:
                    w = getattr(o, v["naam"])
                except Exception:
                    return json.dumps({"soort": None})
                if callable(w):
                    return json.dumps({"soort": "methode"})
                return json.dumps({"soort": "waarde", "w": self.naar_js(w)})
            if v["vraag"] == "roep":
                w = getattr(o, v["naam"])(*[self.naar_py(x) for x in v["args"]])
                return json.dumps({"w": self.naar_js(w)})
            if v["vraag"] == "zet":
                setattr(o, v["naam"], self.naar_py(v["w"]))
                return json.dumps({})
        except Exception as e:
            return json.dumps({"fout": "%s: %s" % (type(e).__name__, e)})


class Test(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctx = verbind()

    def setUp(self):
        self.doc = maak_document(self.ctx)
        self.js = quickjs.Context()
        self.js.add_callable("__uno", Brug(self.ctx, self.doc))
        self.js.eval(SHIM)
        self.js.eval(KIT)

    def tearDown(self):
        self.doc.close(True)

    def kit(self, opdracht, a=None):
        r = json.loads(self.js.eval("JSON.stringify(oaKit(%s, %s))" % (json.dumps(opdracht), json.dumps(a))))
        return r

    def waarde(self, opdracht, a=None):
        r = self.kit(opdracht, a)
        self.assertTrue(r["ok"], r)
        return r["waarde"]

    def test_status(self):
        s = self.waarde("status")
        self.assertEqual(s["soort"], "tekst")
        self.assertEqual(s["naam"], od.naam_van(self.doc))

    def test_blokken_gelijk_aan_python(self):
        self.assertEqual(self.waarde("blokken"), json.loads(json.dumps(od.lees_blokken(self.doc))))

    def test_niveau_en_gewijzigd(self):
        blokken = self.waarde("blokken")
        b = next(x for x in blokken if x.get("soort") != "tabel" and x["niveau"] == 0 and x["tekst"])
        self.waarde("opdracht", {"soort": "niveau", "alinea": b["bron"], "tekst": b["tekst"], "niveau": 2})
        na = {x["bron"]: x for x in self.waarde("blokken") if x.get("soort") != "tabel"}
        self.assertEqual(na[b["bron"]]["niveau"], 2)
        r = self.kit("opdracht", {"soort": "niveau", "alinea": b["bron"], "tekst": "iets anders", "niveau": 1})
        self.assertFalse(r["ok"])
        self.assertEqual(r["fout"], "gewijzigd")

    def test_tabelkop(self):
        tabel = next((x for x in self.waarde("blokken") if x.get("soort") == "tabel"), None)
        if tabel is None:
            self.skipTest("testdocument zonder tabel")
        self.waarde("opdracht", {"soort": "tabelkop", "tabel": tabel["bron"]})
        na = next(x for x in self.waarde("blokken") if x.get("soort") == "tabel" and x["bron"] == tabel["bron"])
        self.assertEqual(na["kopregels"], 1)

    def test_toon(self):
        b = next(x for x in self.waarde("blokken") if x.get("soort") != "tabel")
        self.waarde("toon", {"soort": "alinea", "alinea": b["bron"]})
        self.assertEqual(self.waarde("selectie").strip(), b["tekst"])

    def test_eigenschappen(self):
        self.assertIsNone(self.waarde("eigenschap", {"naam": "oa-id"}))
        self.waarde("schrijf-eigenschap", {"naam": "oa-id", "waarde": "abc"})
        self.waarde("schrijf-eigenschap", {"naam": "Zaak", "waarde": "Z-1"})
        self.assertEqual(self.waarde("eigenschap", {"naam": "oa-id"}), "abc")
        self.waarde("standaardeigenschap", {"naam": "titel", "waarde": "Besluit"})
        self.waarde("standaardeigenschap", {"naam": "trefwoorden", "waarde": "woo, havenkade"})
        self.waarde("standaardeigenschap", {"naam": "status", "waarde": "concept"})
        e = self.waarde("eigenschappen")
        self.assertEqual(e, json.loads(json.dumps(od.lees_eigenschappen(self.doc))))
        self.assertEqual(e["standaard"]["titel"], "Besluit")
        self.assertEqual(e["standaard"]["trefwoorden"], "woo, havenkade")
        self.assertEqual(e["standaard"]["status"], "concept")
        self.assertNotIn("oa-id", e["eigen"])
        r = self.kit("standaardeigenschap", {"naam": "taal", "waarde": "nl-NL"})
        self.assertEqual(r["fout"], "niet-uitvoerbaar")

    def test_tekst_vervangen(self):
        tekst = self.doc.getText()
        tekst.insertString(tekst.getEnd(), "Jan Janssen woont bij Jan. ", False)
        n = self.waarde("tekst-vervangen", {"paren": [{"van": "Jan", "naar": "[PERSOON 1]"}, {"van": "Jan Janssen", "naar": "[PERSOON 2]"}]})
        self.assertEqual(n, 2)
        s = tekst.getString()
        self.assertIn("[PERSOON 2] woont bij [PERSOON 1].", s)

    def test_onbekende_vraag(self):
        r = self.kit("iets")
        self.assertFalse(r["ok"])
        self.assertEqual(r["fout"], "niet-uitvoerbaar")


if __name__ == "__main__":
    unittest.main()
