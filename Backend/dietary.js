const fs = require('fs');
const path = require('path');

const RULES_FILE = path.join(__dirname, 'dietary_rules.json');

// Keys starting with "_" are notes, not restrictions
function loadRules() {
    const rules = JSON.parse(fs.readFileSync(RULES_FILE, 'utf8'));
    for (const key of Object.keys(rules)) {
        if (key.startsWith('_')) {
            delete rules[key];
        }
    }
    return rules;
}

const rules = loadRules();

// Restrictions the dining labels can check; others (e.g. Keto) are ignored
function supportedRestrictions(restrictions) {
    return (restrictions || []).filter(r => rules[r]);
}

// Convert the database's traits column into a list.
// NULL means the dish was scraped before traits were collected (unknown),
// an empty string means the site shows no trait icons for it.
function parseTraits(traitsColumn) {
    if (traitsColumn === null || traitsColumn === undefined) {
        return null;
    }
    return traitsColumn
        .split(',')
        .map(t => t.trim())
        .filter(t => t.length > 0);
}

// Return the restrictions a dish does not satisfy.
// A dish with unknown traits can't be verified, so it conflicts with every restriction.
function getConflicts(traits, restrictions) {
    if (!restrictions || restrictions.length === 0) {
        return [];
    }
    if (traits === null) {
        return [...restrictions];
    }

    return restrictions.filter(restriction => {
        const rule = rules[restriction];
        if (!rule) {
            return false;
        }
        if (rule.exclude && rule.exclude.some(t => traits.includes(t))) {
            return true;
        }
        if (rule.require_any && !rule.require_any.some(t => traits.includes(t))) {
            return true;
        }
        return false;
    });
}

module.exports = {
    rules,
    supportedRestrictions,
    parseTraits,
    getConflicts
};
