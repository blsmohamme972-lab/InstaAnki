const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const TopicSelection = require('../web/topic-selection.js');
const root = path.resolve(__dirname, '..');
const registry = JSON.parse(fs.readFileSync(path.join(root, 'web/data/taxonomy.json'), 'utf8'));
const lessons = JSON.parse(fs.readFileSync(path.join(root, 'web/data/lessons.json'), 'utf8'));
const topics = TopicSelection.create(registry);
const flatten = nodes => nodes.flatMap(node => [node, ...flatten(node.children)]);

test('canonical hierarchy preserves specialty roots and nested subtags', () => {
  assert.deepEqual(topics.roots.map(node => node.id), ['specialty.cardiac', 'specialty.thoracic', 'specialty.vascular']);
  const vascular = flatten([topics.roots[2]]);
  const aortic = vascular.find(node => node.id === 'domain.aortic');
  assert.ok(aortic.children.find(node => node.id === 'condition.aortic_aneurysm').children.some(node => node.id === 'condition.abdominal_aortic_aneurysm'));
  assert.ok(topics.descendants('domain.vascular_physiology').includes('concept.poiseuille_law'));
  assert.ok(!flatten([topics.roots[0]]).some(node => node.id === 'condition.abdominal_aortic_aneurysm'));
  assert.equal(topics.options.length, registry.tags.filter(tag => tag.status === 'active').length);
});

test('All, a single specialty, and multiple topics select the intended daily lessons', () => {
  assert.deepEqual(topics.filterLessons(lessons, []), lessons);
  assert.deepEqual(topics.filterLessons(lessons, ['specialty.thoracic']).map(lesson => lesson.id), ['shahzad2015-q005']);
  assert.deepEqual(topics.filterLessons(lessons, ['specialty.thoracic', 'domain.coronary']).map(lesson => lesson.id), ['shahzad2015-q054', 'shahzad2015-q005']);
  assert.equal(topics.summary([]), 'All topics');
  assert.equal(topics.summary(['specialty.cardiac']), 'Cardiac Surgery');
});

test('selecting a parent includes descendant tags even when the parent is not stored', () => {
  const lesson = { id: 'nested', primarySpecialtyId: 'specialty.vascular', tags: [{ id: 'condition.abdominal_aortic_aneurysm' }] };
  assert.equal(topics.matches(lesson, ['condition.aortic_aneurysm']), true);
  assert.equal(topics.matches(lesson, ['domain.aortic']), true);
  assert.equal(topics.matches(lesson, ['condition.thoracic_aortic_aneurysm']), false);
  const law = { id: 'law', tags: ['concept.poiseuille_law'] };
  assert.equal(topics.matches(law, ['concept.vascular_resistance']), true);
  assert.equal(topics.matches(law, ['domain.vascular_physiology']), true);
});

test('shared eligibility never silently assigns a lesson to another specialty', () => {
  const vascular = lessons.find(lesson => lesson.id === 'shahzad2015-q182');
  assert.equal(topics.matches(vascular, ['specialty.vascular']), true);
  assert.equal(topics.matches(vascular, ['specialty.cardiac']), false);
  assert.equal(topics.matches(vascular, ['specialty.thoracic']), false);
  assert.equal(topics.matches({ ...vascular, secondarySpecialtyIds: ['specialty.cardiac'] }, ['specialty.cardiac']), true);
  assert.equal(topics.matches({ id: 'legacy', specialty: 'Cardiac Surgery' }, ['specialty.cardiac']), true);
});

test('search finds aliases, nested tags, and parent context while retaining hierarchy', () => {
  assert.ok(topics.search('AAA').some(option => option.id === 'condition.abdominal_aortic_aneurysm'));
  assert.ok(topics.search('vascular hagen poiseuille').some(option => option.id === 'concept.poiseuille_law'));
  const results = flatten(topics.tree('extralobar'));
  assert.deepEqual(results.map(option => option.id), ['specialty.thoracic', 'domain.lung', 'condition.pulmonary_sequestration', 'condition.extralobar_pulmonary_sequestration']);
  assert.ok(topics.search('aortic disease').some(option => option.id === 'condition.stanford_type_a_dissection'));
  assert.ok(topics.get('condition.extralobar_pulmonary_sequestration').breadcrumb.includes('Pulmonary Sequestration'));
  assert.deepEqual(topics.search('not a registered topic 9876'), []);
});

test('unknown, deprecated, and malformed selections do not broaden to All', () => {
  assert.deepEqual(topics.normalize(['specialty.cardiac', 'specialty.cardiac', 'unknown', null, '__proto__']), ['specialty.cardiac']);
  assert.deepEqual(topics.filterLessons(lessons, ['unknown']), []);
  assert.equal(topics.matches(lessons[0], 'specialty.cardiac'), false);
  assert.equal(topics.matches(null, []), false);
  assert.equal(topics.summary(['unknown']), 'Unavailable topics');
  const changed = JSON.parse(JSON.stringify(registry));
  changed.tags.find(tag => tag.id === 'concept.poiseuille_law').status = 'deprecated';
  const updated = TopicSelection.create(changed);
  assert.equal(updated.get('concept.poiseuille_law'), null);
  assert.deepEqual(updated.normalize(['concept.poiseuille_law']), []);
});

test('filtering preserves source order and inputs without mutation', () => {
  const source = JSON.stringify(lessons), selection = ['specialty.thoracic'];
  const selected = topics.filterLessons(lessons, selection);
  assert.equal(selected[0].id, 'shahzad2015-q005');
  assert.equal(JSON.stringify(lessons), source);
  assert.deepEqual(selection, ['specialty.thoracic']);
  assert.notEqual(topics.filterLessons(lessons, []), lessons);
});

test('invalid registries and cyclic parent metadata are handled without recursion errors', () => {
  assert.deepEqual(TopicSelection.create(null).roots, []);
  const malformed = JSON.parse(JSON.stringify(registry));
  const a = malformed.tags.find(tag => tag.id === 'concept.vascular_resistance');
  const b = malformed.tags.find(tag => tag.id === 'concept.poiseuille_law');
  a.parent_id = b.id;
  assert.doesNotThrow(() => TopicSelection.create(malformed).tree('poiseuille'));
  assert.ok(TopicSelection.create(malformed).options.length > 0);
});

test('the same pure helper loads directly in the offline browser without CommonJS', () => {
  const context = vm.createContext({});
  vm.runInContext(fs.readFileSync(path.join(root, 'web/topic-selection.js'), 'utf8'), context);
  assert.equal(typeof context.TopicSelection.create, 'function');
  assert.equal(context.TopicSelection.create(registry).summary([]), 'All topics');
});
