# Taxonomy changelog

## 1.1.0 - 2026-11-07

Added the optional `concept_ids` annotation facet and six canonical IDs:

| ID | Canonical English label |
|---|---|
| `domain.vascular_physiology` | Vascular Physiology |
| `concept.coronary_dominance` | Coronary Dominance |
| `concept.vascular_resistance` | Vascular Resistance |
| `concept.poiseuille_law` | Poiseuille's Law |
| `condition.pulmonary_sequestration` | Pulmonary Sequestration |
| `condition.extralobar_pulmonary_sequestration` | Extralobar Pulmonary Sequestration |

The new physiology domain permits foundational vessel-flow questions to be indexed without implying an arterial disease. The extralobar condition is a child of Pulmonary Sequestration, and Poiseuille's Law is a child of Vascular Resistance. Parent categories remain available through the hierarchy.

The release contains 124 canonical entries. All 118 existing tag objects and IDs are unchanged. No IDs are deprecated or replaced. The original 1.0.0 registry, schema and examples remain available for existing content packs.

The current schema, latest registry alias, synthetic examples and tagging documentation are updated together. The migration contract is recorded in `migration.v1.0-to-v1.1.json`. No learning-history migration is required or performed.

## 1.0.0 - 2026-11-07

Initial controlled English vocabulary with 118 canonical entries and the three fixed specialty roots: Cardiac Surgery, Thoracic Surgery and Vascular Surgery.
