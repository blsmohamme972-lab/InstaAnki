'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

// These regression suites exercise the original, deliberately small collection:
// one lesson in each specialty, including its calibrated clinical targets.
// The open-reference collection has its own reference-batch-browser.cjs suite.
// Load the real production records so a removed or broken starter cannot pass by
// falling back to an obsolete copy of its lesson content.
const lessonIds = Object.freeze([
  'shahzad2015-q054',
  'shahzad2015-q005',
  'shahzad2015-q182',
]);
const bookId = 'shahzad-raja-2015-200-practice-questions';
const label = 'Raja starter fixture';

function loadRajaStarterFixture(web) {
  const library = JSON.parse(fs.readFileSync(path.join(web, 'data/lessons.json'), 'utf8'));
  const lessons = lessonIds.map(id => {
    const matches = library.filter(lesson => lesson.id === id);
    assert.equal(matches.length, 1, `Expected exactly one production starter lesson: ${id}`);
    return matches[0];
  });
  const books = JSON.parse(fs.readFileSync(path.join(web, 'data/books.json'), 'utf8'))
    .filter(book => book.id === bookId);
  assert.equal(books.length, 1, 'The original Raja publication must remain in the production catalog');
  return { id: 'raja-starter-three', label, lessons, books };
}

async function routeRajaStarterFixture(context, fixture) {
  await context.route('**/data/lessons.json', route => route.fulfill({ json: fixture.lessons }));
  await context.route('**/data/books.json', route => route.fulfill({ json: fixture.books }));
}

module.exports = { loadRajaStarterFixture, routeRajaStarterFixture };
