# -*- coding: utf-8 -*-
"""Test oa_pii.Inzage (originele waarden tijdelijk in de tekst) tegen een echte LibreOffice (headless)."""
import os
import sys
import tempfile
import unittest
import zipfile

import uno
import unohelper
from com.sun.star.frame import XStatusListener

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "pythonpath"))
import oa_pii as op  # noqa: E402
from oa_kern import NietUitvoerbaar  # noqa: E402
from test_document import p, verbind  # noqa: E402

TEKST = "Mevrouw Jansen woont aan de Havenkade 12. Jansen belt morgen."
WAARDEN = [{"plaatshouder": "[PERSOON 1]", "waarde": "Jansen"}, {"plaatshouder": "[ADRES 1]", "waarde": "Havenkade 12"}]


class Stand(unohelper.Base, XStatusListener):
    aan = None

    def statusChanged(self, e):
        self.aan = e.IsEnabled

    def disposing(self, e):
        pass


def inhoud_xml(pad):
    with zipfile.ZipFile(pad) as z:
        return z.read("content.xml").decode("utf-8")


class TestInzage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctx = verbind()
        cls.desktop = cls.ctx.ServiceManager.createInstanceWithContext("com.sun.star.frame.Desktop", cls.ctx)
        cls.helper = cls.ctx.ServiceManager.createInstanceWithContext("com.sun.star.frame.DispatchHelper", cls.ctx)

    def setUp(self):
        self.map = tempfile.mkdtemp()
        self.pad = os.path.join(self.map, "stuk.odt")
        doc = self.desktop.loadComponentFromURL("private:factory/swriter", "_blank", 0, (p("Hidden", True),))
        doc.getText().setString(TEKST)
        op.markeer(doc, [{"van": "Jansen", "plaatshouder": "[PERSOON 1]", "ppl": 1}, {"van": "Havenkade 12", "plaatshouder": "[ADRES 1]", "ppl": 1}])
        op.zet_definitief(doc)
        doc.storeToURL(uno.systemPathToFileUrl(self.pad), ())
        doc.close(True)
        self.doc = self.desktop.loadComponentFromURL(uno.systemPathToFileUrl(self.pad), "_blank", 0, (p("Hidden", True),))
        self.inzage = op.Inzage(self.ctx, self.doc)

    def tearDown(self):
        try:
            self.inzage.verberg()
        finally:
            self.doc.close(True)

    def tekst(self):
        return self.doc.getText().getString()

    def dispatch(self, cmd, *args):
        self.helper.executeDispatch(self.doc.getCurrentController().getFrame(), cmd, "", 0, tuple(args))

    def test_tonen_en_verbergen(self):
        self.assertEqual(self.tekst(), "Mevrouw [PERSOON 1] woont aan de [ADRES 1]. [PERSOON 1] belt morgen.")
        self.assertEqual(self.inzage.toon(WAARDEN), 3)
        self.assertTrue(self.inzage.actief)
        self.assertEqual(self.tekst(), TEKST)
        self.assertTrue(self.doc.isReadonly())
        self.assertFalse(self.doc.isModified())
        # De plekken blijven herkenbaar (bladwijzers met dezelfde naam).
        self.assertEqual([x["plaatshouder"] for x in op.lees_plekken(self.doc)], ["[PERSOON 1]", "[ADRES 1]", "[PERSOON 1]"])
        self.inzage.verberg()
        self.assertFalse(self.inzage.actief)
        self.assertEqual(self.tekst(), "Mevrouw [PERSOON 1] woont aan de [ADRES 1]. [PERSOON 1] belt morgen.")
        self.assertFalse(self.doc.isReadonly())
        self.assertFalse(self.doc.isModified())
        # Ongedaan maken brengt de originelen niet terug.
        um = self.doc.getUndoManager()
        while um.isUndoPossible():
            um.undo()
        self.assertNotIn("Jansen", self.tekst())

    def test_alleen_waarden_die_je_mag_zien(self):
        self.assertEqual(self.inzage.toon(WAARDEN[:1]), 2)
        self.assertEqual(self.tekst(), "Mevrouw Jansen woont aan de [ADRES 1]. Jansen belt morgen.")

    def test_niet_typen_niet_opslaan_niet_afdrukken(self):
        voor = os.path.getmtime(self.pad)
        self.inzage.toon(WAARDEN)
        self.doc.getCurrentController().getViewCursor().gotoEnd(False)
        self.dispatch(".uno:InsertText", p("Text", " GETYPT"))
        self.assertNotIn("GETYPT", self.tekst())
        self.dispatch(".uno:Save")
        self.dispatch(".uno:EditDoc")
        self.assertTrue(self.doc.isReadonly(), "Bewerken hoort onderschept te zijn")
        self.dispatch(".uno:Print")
        self.assertEqual(os.path.getmtime(self.pad), voor)
        self.assertFalse(self.doc.isModified())
        self.assertNotIn("Jansen", inhoud_xml(self.pad))
        # Menu's en werkbalken zien Opslaan, Afdrukken en Bewerken als uitgeschakeld.
        frame = self.doc.getCurrentController().getFrame()
        for cmd in (".uno:Save", ".uno:SaveAs", ".uno:ExportDirectToPDF", ".uno:Print", ".uno:EditDoc", ".uno:SendMail"):
            url = uno.createUnoStruct("com.sun.star.util.URL")
            url.Complete = cmd
            stand = Stand()
            frame.queryDispatch(url, "", 0).addStatusListener(stand, url)
            self.assertIs(stand.aan, False, cmd)
        url = uno.createUnoStruct("com.sun.star.util.URL")
        url.Complete = ".uno:Copy"
        kopieer = frame.queryDispatch(url, "", 0)  # zonder selectie kan dit leeg zijn
        if kopieer is not None:
            stand = Stand()
            kopieer.addStatusListener(stand, url)
            self.assertIsNot(stand.aan, False, "kopiëren wordt niet door de inzage geblokkeerd")

    def test_vangnet_bij_opslaan_buiten_de_knoppen_om(self):
        self.inzage.toon(WAARDEN)
        kopie = os.path.join(self.map, "kopie.odt")
        self.doc.storeToURL(uno.systemPathToFileUrl(kopie), ())
        self.assertNotIn("Jansen", inhoud_xml(kopie))
        self.assertIn("[PERSOON 1]", inhoud_xml(kopie))
        # Daarna staan de originelen weer in beeld, en verbergen werkt gewoon.
        self.assertEqual(self.tekst(), TEKST)
        self.inzage.verberg()
        self.assertNotIn("Jansen", self.tekst())
        self.assertFalse(self.doc.isReadonly())

    def test_alleen_opgeslagen_en_ongewijzigd(self):
        self.doc.getText().insertString(self.doc.getText().getEnd(), " extra", False)
        self.assertTrue(self.doc.isModified())
        with self.assertRaises(NietUitvoerbaar):
            self.inzage.toon(WAARDEN)
        self.assertNotIn("Jansen", self.tekst())
        nieuw = self.desktop.loadComponentFromURL("private:factory/swriter", "_blank", 0, (p("Hidden", True),))
        try:
            with self.assertRaises(NietUitvoerbaar):
                op.Inzage(self.ctx, nieuw).toon(WAARDEN)
        finally:
            nieuw.close(True)


if __name__ == "__main__":
    unittest.main()


class TestInzageBrug(unittest.TestCase):
    """Via de brug: tonen, dan weigert de brug alles wat de inhoud leest of wijzigt."""

    def test_brug(self):
        import json
        import urllib.request
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
        import assistent
        ctx = verbind()
        desktop = ctx.ServiceManager.createInstanceWithContext("com.sun.star.frame.Desktop", ctx)
        pad = os.path.join(tempfile.mkdtemp(), "stuk.odt")
        doc = desktop.loadComponentFromURL("private:factory/swriter", "_blank", 0, (p("Hidden", True),))
        doc.getText().setString(TEKST)
        op.markeer(doc, [{"van": "Jansen", "plaatshouder": "[PERSOON 1]", "ppl": 1}])
        doc.storeToURL(uno.systemPathToFileUrl(pad), ())
        doc.close(True)
        doc = desktop.loadComponentFromURL(uno.systemPathToFileUrl(pad), "_blank", 0, (p("Hidden", True),))
        brug = assistent.Brug(ctx, doc, "https://oa.voorbeeld.nl")

        def vraag(methode, pad_, lichaam=None):
            r = urllib.request.Request("http://127.0.0.1:%d%s" % (brug.poort, pad_), method=methode,
                                       data=json.dumps(lichaam).encode() if lichaam is not None else None)
            r.add_header("Authorization", "Bearer " + brug.sleutel)
            r.add_header("Origin", "https://oa.voorbeeld.nl")
            r.add_header("Content-Type", "application/json")
            try:
                with urllib.request.urlopen(r, timeout=30) as a:
                    return a.status, json.loads(a.read() or b"{}")
            except urllib.error.HTTPError as e:
                return e.code, json.loads(e.read() or b"{}")

        try:
            self.assertEqual(vraag("POST", "/pii/inzien", {"waarden": WAARDEN}), (200, {"getoond": 2}))
            self.assertEqual(vraag("GET", "/pii/inzage"), (200, {"actief": True}))
            code, b = vraag("GET", "/blokken")
            self.assertEqual(code, 422)
            self.assertIn("Verberg ze eerst", b["melding"])
            self.assertEqual(vraag("GET", "/bestand")[0], 422)
            self.assertEqual(vraag("GET", "/pii/plekken")[0], 200)
            self.assertEqual(vraag("GET", "/status")[0], 200)
            self.assertEqual(vraag("POST", "/pii/verbergen", {})[0], 200)
            self.assertEqual(vraag("GET", "/pii/inzage"), (200, {"actief": False}))
            self.assertEqual(vraag("GET", "/blokken")[0], 200)
            # Opnieuw tonen en het paneel sluiten: de originelen gaan weg.
            vraag("POST", "/pii/inzien", {"waarden": WAARDEN})
            self.assertIn("Jansen", doc.getText().getString())
        finally:
            brug.stop()
            self.assertNotIn("Jansen", doc.getText().getString())
            self.assertFalse(doc.isReadonly())
            doc.close(True)
