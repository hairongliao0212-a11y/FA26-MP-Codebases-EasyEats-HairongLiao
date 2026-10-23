// Tests for dietary restriction filtering in the API.
// Run from Backend/ with the project venv active (the meal-plan test runs python3):
//     npm test
// The server is started against a temporary database and users file, so real data is untouched.

const test = require('node:test');
const assert = require('node:assert');
const { spawn } = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');
const sqlite3 = require('sqlite3');

const dietary = require('../dietary');

const PORT = 3999;
const BASE = `http://localhost:${PORT}`;

// [name, category, traits, calories, protein, fat, carbs]; traits null = unknown
const DISHES = [
    ['Grilled Chicken', 'Entrees', 'Halal', 220, 35, 6, 0],
    ['Tofu Stir Fry', 'Entrees', 'Soy, Vegan, Vegetarian', 250, 14, 10, 25],
    ['Cheese Pizza', 'Entrees', 'Gluten, Milk, Wheat, Vegetarian', 300, 12, 12, 35],
    ['Shrimp Pasta', 'Entrees', 'Gluten, Shellfish, Wheat', 400, 20, 14, 45],
    ['Peanut Noodles', 'Entrees', 'Gluten, Peanuts, Soy, Wheat, Vegan, Vegetarian', 380, 12, 16, 48],
    ['Scrambled Eggs', 'Entrees', 'Eggs, Milk, Vegetarian', 180, 12, 13, 2],
    ['Mystery Casserole', 'Entrees', null, 350, 18, 15, 30],
    ['Steamed Broccoli', 'Vegetables', 'Vegan, Vegetarian', 50, 4, 0.5, 10],
    ['Brown Rice', 'Grains', 'Vegan, Vegetarian', 200, 5, 1.5, 42],
];
const TRAITS = Object.fromEntries(DISHES.map(d => [d[0], dietary.parseTraits(d[2])]));

const USERS = [
    { id: 1, email: 'none@test.edu', dietary_restrictions: [] },
    { id: 2, email: 'vegan@test.edu', dietary_restrictions: ['Vegan'] },
    { id: 3, email: 'allergies@test.edu', dietary_restrictions: ['Nut Allergy', 'Shellfish Allergy', 'Egg Allergy'] },
    { id: 4, email: 'keto@test.edu', dietary_restrictions: ['Keto', 'Gluten-Free'] },
].map(u => ({ ...u, password_hash: 'x:y', goal: 'Maintain', calories: 2000 }));

let tmpDir;
let server;

function createDatabase(dbFile) {
    return new Promise((resolve, reject) => {
        const db = new sqlite3.Database(dbFile);
        db.serialize(() => {
            db.run(`CREATE TABLE nutrition_data (
                id INTEGER PRIMARY KEY AUTOINCREMENT, dining_hall TEXT, service TEXT, date TEXT,
                meal_type TEXT, category TEXT, name TEXT, traits TEXT, serving_size TEXT,
                calories REAL, total_fat REAL, saturated_fat REAL, trans_fat REAL, cholesterol REAL,
                sodium REAL, potassium REAL, total_carbohydrate REAL, dietary_fiber REAL,
                sugars REAL, protein REAL)`);
            const insert = db.prepare(`INSERT INTO nutrition_data
                (dining_hall, service, date, meal_type, category, name, traits, serving_size,
                 calories, protein, total_fat, total_carbohydrate, dietary_fiber, sugars, sodium)
                VALUES (?, 'Main', 'Thursday, October 22, 2026', 'Lunch', ?, ?, ?, '1 serving', ?, ?, ?, ?, 2, 1, 0.3)`);
            for (const [name, category, traits, cal, protein, fat, carbs] of DISHES) {
                insert.run('Illinois Street Dining Center (ISR)', category, name, traits, cal, protein, fat, carbs);
            }
            insert.finalize();
        });
        db.close(err => (err ? reject(err) : resolve()));
    });
}

async function waitForServer() {
    for (let i = 0; i < 50; i++) {
        try {
            const res = await fetch(`${BASE}/health`);
            if (res.ok) return;
        } catch (e) {
            // Not up yet
        }
        await new Promise(r => setTimeout(r, 100));
    }
    throw new Error('Server did not start');
}

async function get(urlPath) {
    const res = await fetch(BASE + urlPath);
    return { status: res.status, body: await res.json() };
}

test.before(async () => {
    tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'easyeats-test-'));
    const dbFile = path.join(tmpDir, 'nutrition.db');
    const usersFile = path.join(tmpDir, 'users.json');
    await createDatabase(dbFile);
    fs.writeFileSync(usersFile, JSON.stringify({ users: USERS }));

    server = spawn('node', [path.join(__dirname, '..', 'server.js')], {
        env: { ...process.env, PORT: String(PORT), NUTRITION_DB: dbFile, USERS_DB: usersFile },
        stdio: 'ignore',
    });
    await waitForServer();
});

test.after(() => {
    server.kill();
    fs.rmSync(tmpDir, { recursive: true, force: true });
});

test('getConflicts applies exclude and require_any rules', () => {
    assert.deepStrictEqual(dietary.getConflicts(['Peanuts'], ['Nut Allergy']), ['Nut Allergy']);
    assert.deepStrictEqual(dietary.getConflicts(['Vegetarian'], ['Vegan', 'Vegetarian']), ['Vegan']);
    assert.deepStrictEqual(dietary.getConflicts(['Vegan'], ['Vegetarian']), []);
    assert.deepStrictEqual(dietary.getConflicts(null, ['Halal']), ['Halal']);
    assert.deepStrictEqual(dietary.getConflicts([], []), []);
});

test('parseTraits keeps unknown (null) separate from no traits', () => {
    assert.strictEqual(dietary.parseTraits(null), null);
    assert.deepStrictEqual(dietary.parseTraits(''), []);
    assert.deepStrictEqual(dietary.parseTraits('Eggs, Milk'), ['Eggs', 'Milk']);
});

test('recommendations for a user without restrictions include every dish', async () => {
    const { status, body } = await get('/api/recommendations/1?dining_hall=ISR&meal_type=Lunch');
    assert.strictEqual(status, 200);
    assert.strictEqual(body.count, DISHES.length);
    assert.deepStrictEqual(body.applied_restrictions, []);
});

test('recommendations for a vegan user are all vegan', async () => {
    const { body } = await get('/api/recommendations/2?dining_hall=ISR&meal_type=Lunch');
    const names = body.recommendations.map(f => f.name).sort();
    assert.deepStrictEqual(names, ['Brown Rice', 'Peanut Noodles', 'Steamed Broccoli', 'Tofu Stir Fry']);
    assert.deepStrictEqual(body.applied_restrictions, ['Vegan']);
});

test('recommendations exclude every allergen and dishes with unknown traits', async () => {
    const { body } = await get('/api/recommendations/3?dining_hall=ISR&meal_type=Lunch');
    const names = body.recommendations.map(f => f.name);
    assert.ok(names.length > 0);
    for (const name of ['Peanut Noodles', 'Shrimp Pasta', 'Scrambled Eggs', 'Mystery Casserole']) {
        assert.ok(!names.includes(name), `${name} should be excluded`);
    }
    for (const food of body.recommendations) {
        assert.deepStrictEqual(food.conflicts, []);
    }
});

test('restrictions without dining labels (Keto) are not claimed as applied', async () => {
    const { body } = await get('/api/recommendations/4?dining_hall=ISR&meal_type=Lunch');
    assert.deepStrictEqual(body.applied_restrictions, ['Gluten-Free']);
});

test('all foods list keeps every dish but marks conflicts for the user', async () => {
    const { body } = await get('/api/dining-halls/ISR/foods?meal_type=Lunch&user_id=2');
    assert.strictEqual(body.count, DISHES.length);
    const byName = Object.fromEntries(body.foods.map(f => [f.name, f]));
    assert.deepStrictEqual(byName['Cheese Pizza'].conflicts, ['Vegan']);
    assert.deepStrictEqual(byName['Brown Rice'].conflicts, []);
    assert.deepStrictEqual(byName['Cheese Pizza'].traits, ['Gluten', 'Milk', 'Wheat', 'Vegetarian']);
    assert.strictEqual(byName['Mystery Casserole'].traits, null);
});

test('all foods list without user_id has no conflicts', async () => {
    const { body } = await get('/api/dining-halls/ISR/foods?meal_type=Lunch');
    assert.ok(body.foods.every(f => f.conflicts.length === 0));
});

test('meal plan for a user follows their restrictions', async () => {
    for (let i = 0; i < 5; i++) {
        const { status, body } = await get('/api/meal-plan?calories=600&dining_hall=ISR&meal_type=Lunch&user_id=3');
        assert.strictEqual(status, 200, JSON.stringify(body));
        assert.deepStrictEqual(body.applied_restrictions, ['Nut Allergy', 'Shellfish Allergy', 'Egg Allergy']);
        for (const item of body.items) {
            const conflicts = dietary.getConflicts(TRAITS[item.name], body.applied_restrictions);
            assert.deepStrictEqual(conflicts, [], `${item.name} breaks ${conflicts}`);
        }
    }
});
