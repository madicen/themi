const test = require("node:test");
const assert = require("node:assert/strict");
const { parseList, MAX_QTY } = require("../lib/list.js");

test("one item per line, quantity 1 by default", () => {
  assert.deepEqual(parseList("eggs\nbananas"), [
    { key: "eggs", name: "eggs", qty: 1 },
    { key: "bananas", name: "bananas", qty: 1 },
  ]);
});

test("a number in front is the quantity", () => {
  assert.deepEqual(parseList("2 oat milk\n3x apples\nbread x2"), [
    { key: "oat milk", name: "oat milk", qty: 2 },
    { key: "apples", name: "apples", qty: 3 },
    { key: "bread", name: "bread", qty: 2 },
  ]);
});

test("numbers that are part of the name stay in it", () => {
  assert.deepEqual(
    parseList("7up\n1% milk").map((i) => [i.name, i.qty]),
    [
      ["7up", 1],
      ["1% milk", 1],
    ],
  );
});

test("blank lines, spaces and list bullets are ignored", () => {
  assert.deepEqual(
    parseList("\n  - eggs  \n\n* 2  oat   milk\n• rice\n1. beans\n   \n").map((i) => [i.name, i.qty]),
    [
      ["eggs", 1],
      ["oat milk", 2],
      ["rice", 1],
      ["beans", 1],
    ],
  );
});

test("duplicates are merged, ignoring case, and their quantities added", () => {
  assert.deepEqual(parseList("Eggs\n2 oat milk\neggs\noat  milk"), [
    { key: "eggs", name: "Eggs", qty: 2 },
    { key: "oat milk", name: "oat milk", qty: 3 },
  ]);
});

test("quantities are kept between 1 and the store's limit", () => {
  assert.equal(parseList("0 eggs")[0].qty, 1);
  assert.equal(parseList("500 eggs")[0].qty, MAX_QTY);
  assert.equal(parseList("15 eggs\n15 eggs")[0].qty, MAX_QTY);
});

test("an empty list is empty", () => {
  assert.deepEqual(parseList(""), []);
  assert.deepEqual(parseList(" \n\n "), []);
  assert.deepEqual(parseList(undefined), []);
});
