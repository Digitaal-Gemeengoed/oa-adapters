import { test } from "node:test";
import assert from "node:assert/strict";
import { extensieHerkomst } from "../src/collabora/kit-tekstverwerker.ts";

const hier = (url: string) => new URL(url) as unknown as Location;

test("herkomst van de extensie: alleen office.<domein> naast oa.<domein>", () => {
  const oa = hier("https://oa.voorbeeld.nl/collabora-extensie/");
  assert.equal(extensieHerkomst("?herkomst=https%3A%2F%2Foffice.voorbeeld.nl", oa), "https://office.voorbeeld.nl");
  assert.equal(extensieHerkomst("?herkomst=https://office.voorbeeld.nl/", oa), "https://office.voorbeeld.nl");
  assert.equal(extensieHerkomst("?herkomst=https://office.kwaad.nl", oa), null);
  assert.equal(extensieHerkomst("?herkomst=https://voorbeeld.nl.kwaad.nl", oa), null);
  assert.equal(extensieHerkomst("?herkomst=http://office.voorbeeld.nl", oa), null);
  assert.equal(extensieHerkomst("?herkomst=https://office.voorbeeld.nl/pad", oa), null);
  assert.equal(extensieHerkomst("", oa), null);
  assert.equal(extensieHerkomst("?herkomst=http://localhost:9201", hier("http://localhost:8443/collabora-extensie/")), "http://localhost:9201");
  assert.equal(extensieHerkomst("?herkomst=http://localhost:9201", oa), null);
});
