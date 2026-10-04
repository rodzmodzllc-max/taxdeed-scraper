// Runs tests/python/fixtures/screening_cases.json through public/screening.js
// and prints the results as JSON (one per case, then one per buy-box case).
// Driven by tests/python/test_investor_screening.py.
import fs from "node:fs";
import { screenProperty, passesBuyBox } from "../../public/screening.js";
const data = JSON.parse(fs.readFileSync(new URL("./fixtures/screening_cases.json", import.meta.url), "utf8"));
const out = {
  cases: data.cases.map(c => screenProperty(c.row)),
  buy_box: data.buy_box.map(c => passesBuyBox(c.row, screenProperty(c.row), c.box))
};
process.stdout.write(JSON.stringify(out));
