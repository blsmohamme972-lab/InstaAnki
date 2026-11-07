/* Canonical daily-topic selection. No storage, scheduling, or DOM side effects. */
(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.TopicSelection = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  const ROOT_IDS = ['specialty.cardiac', 'specialty.thoracic', 'specialty.vascular'];
  const FACETS = ['specialty', 'domain', 'condition', 'procedure', 'concept', 'anatomy', 'focus', 'phase', 'population'];
  const validId = id => typeof id === 'string' && /^[a-zA-Z0-9][a-zA-Z0-9._-]{0,119}$/.test(id) && !['__proto__', 'constructor', 'prototype'].includes(id);
  const terms = value => String(value || '').normalize('NFKD').replace(/[\u0300-\u036f]/g, '').toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim();

  function create(registry) {
    const tags = new Map();
    for (const raw of Array.isArray(registry?.tags) ? registry.tags : []) {
      if (!raw || raw.status !== 'active' || !validId(raw.id) || typeof raw.label !== 'string' || !raw.label.trim() || tags.has(raw.id)) continue;
      tags.set(raw.id, {
        id: raw.id, label: raw.label, facet: raw.facet || raw.id.split('.')[0],
        parentId: validId(raw.parent_id) ? raw.parent_id : null,
        specialtyIds: Array.isArray(raw.specialty_ids) ? [...new Set(raw.specialty_ids.filter(id => ROOT_IDS.includes(id)))] : [],
        aliases: Array.isArray(raw.aliases) ? raw.aliases.filter(alias => typeof alias === 'string') : [],
      });
    }
    const rootIds = ROOT_IDS.filter(id => tags.get(id)?.facet === 'specialty');
    const rootSet = new Set(rootIds);
    // Invalid or cyclic parent references never produce an infinite tree.
    for (const tag of tags.values()) {
      let id = tag.parentId;
      const seen = new Set([tag.id]);
      while (id && tags.has(id)) {
        if (seen.has(id)) { tag.parentId = null; break; }
        seen.add(id); id = tags.get(id).parentId;
      }
      if (tag.parentId && !tags.has(tag.parentId)) tag.parentId = null;
    }
    const ancestors = id => {
      const result = [], seen = new Set([id]);
      let parent = tags.get(id)?.parentId;
      while (parent && tags.has(parent) && !seen.has(parent)) {
        result.push(parent); seen.add(parent); parent = tags.get(parent).parentId;
      }
      return result;
    };
    const scope = id => {
      if (rootSet.has(id)) return [id];
      const tag = tags.get(id);
      if (!tag) return [];
      if (tag.specialtyIds.length) return tag.specialtyIds.filter(s => rootSet.has(s));
      for (const parent of ancestors(id)) {
        if (rootSet.has(parent)) return [parent];
        if (tags.get(parent).specialtyIds.length) return tags.get(parent).specialtyIds.filter(s => rootSet.has(s));
      }
      return [];
    };
    const compare = (a, b) => {
      const aFacet = FACETS.indexOf(a.facet), bFacet = FACETS.indexOf(b.facet);
      return (aFacet < 0 ? FACETS.length : aFacet) - (bFacet < 0 ? FACETS.length : bFacet) || a.label.localeCompare(b.label, 'en') || a.id.localeCompare(b.id);
    };
    const options = [...tags.values()].map(tag => {
      const parentIds = ancestors(tag.id).reverse().filter(id => !rootSet.has(id));
      const specialtyIds = scope(tag.id);
      const paths = specialtyIds.map(rootId => {
        const pathIds = rootId === tag.id ? [rootId] : [rootId, ...parentIds, tag.id];
        return { rootId, pathIds, pathLabels: pathIds.map(id => tags.get(id).label) };
      });
      const rootLabels = specialtyIds.map(id => tags.get(id).label);
      const breadcrumb = rootSet.has(tag.id) ? 'Specialty' : [rootLabels.join(' / '), ...parentIds.map(id => tags.get(id).label)].filter(Boolean).join(' › ');
      return Object.freeze({ ...tag, specialtyIds: Object.freeze(specialtyIds), aliases: Object.freeze([...tag.aliases]), ancestorIds: Object.freeze(parentIds), paths: Object.freeze(paths), breadcrumb });
    }).sort(compare);
    const byId = new Map(options.map(option => [option.id, option]));
    const normalize = ids => Array.isArray(ids) ? [...new Set(ids.filter(id => typeof id === 'string' && byId.has(id)))] : [];
    const roots = rootIds.map(rootId => {
      const eligible = options.filter(option => option.id !== rootId && !rootSet.has(option.id) && option.specialtyIds.includes(rootId));
      const ids = new Set(eligible.map(option => option.id));
      const children = new Map();
      for (const option of eligible) {
        const parent = ids.has(option.parentId) ? option.parentId : rootId;
        if (!children.has(parent)) children.set(parent, []);
        children.get(parent).push(option);
      }
      const node = option => Object.freeze({ ...option, children: Object.freeze((children.get(option.id) || []).sort(compare).map(node)) });
      return node(byId.get(rootId));
    });
    const searchIndex = new Map(options.map(option => {
      const related = [...option.ancestorIds, ...option.specialtyIds].map(id => tags.get(id)).filter(Boolean);
      return [option.id, terms([option.id, option.label, ...option.aliases, ...related.flatMap(tag => [tag.label, ...tag.aliases])].join(' '))];
    }));
    const search = query => {
      const needles = terms(query).split(' ').filter(Boolean);
      return options.filter(option => needles.every(needle => searchIndex.get(option.id).includes(needle)));
    };
    const tree = query => {
      if (!terms(query)) return roots;
      const visible = new Set(search(query).map(option => option.id));
      const prune = node => {
        const children = node.children.map(prune).filter(Boolean);
        return visible.has(node.id) || children.length ? { ...node, children } : null;
      };
      return roots.map(prune).filter(Boolean);
    };
    const lessonIds = lesson => {
      const ids = new Set();
      for (const raw of Array.isArray(lesson.tags) ? lesson.tags : []) {
        const id = typeof raw === 'string' ? raw : raw?.id;
        if (byId.has(id)) ids.add(id);
      }
      for (const key of ['primarySpecialtyId', 'primaryDomainId', 'primaryFocusId']) if (byId.has(lesson[key])) ids.add(lesson[key]);
      for (const key of ['secondarySpecialtyIds', 'specialtyIds']) {
        for (const id of Array.isArray(lesson[key]) ? lesson[key] : []) if (rootSet.has(id)) ids.add(id);
      }
      // Older packages may have the canonical specialty label but no ID.
      for (const rootId of rootIds) if (lesson.specialty === byId.get(rootId).label) ids.add(rootId);
      return ids;
    };
    const matches = (lesson, selectedIds = []) => {
      if (!lesson || typeof lesson !== 'object' || !Array.isArray(selectedIds)) return false;
      if (!selectedIds.length) return true;
      const selected = normalize(selectedIds);
      if (!selected.length) return false;
      const assigned = lessonIds(lesson);
      return selected.some(id => {
        // Eligibility in specialty_ids is not an assignment. A shared concept
        // must not turn a vascular lesson into a cardiac or thoracic lesson.
        if (rootSet.has(id)) return assigned.has(id);
        return [...assigned].some(actual => actual === id || ancestors(actual).includes(id));
      });
    };
    const filterLessons = (lessons, selectedIds = []) => (Array.isArray(lessons) ? lessons : []).filter(lesson => matches(lesson, selectedIds));
    const summary = (ids = []) => {
      if (Array.isArray(ids) && !ids.length) return 'All topics';
      const selected = normalize(ids);
      if (!selected.length) return 'Unavailable topics';
      const labels = selected.map(id => byId.get(id).label);
      return labels.length <= 2 ? labels.join(', ') : `${labels.slice(0, 2).join(', ')} + ${labels.length - 2} more`;
    };
    return Object.freeze({
      roots: Object.freeze(roots), options: Object.freeze(options),
      get: id => byId.get(id) || null,
      normalize, matches, filterLessons, search, tree, summary, ancestors,
      descendants: id => byId.has(id) ? options.filter(option => ancestors(option.id).includes(id)).map(option => option.id) : [],
    });
  }
  return Object.freeze({ create });
});
