"""
Tests for dietary restriction support in the scraper, database loader and meal planner.

Run from the repository root with the project venv:
    python -m unittest discover -s Backend/tests -v
"""
import json
import os
import re
import sqlite3
import sys
import tempfile
import unittest

import pandas as pd

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_DIR = os.path.dirname(BACKEND_DIR)
sys.path.insert(0, os.path.join(BACKEND_DIR, 'scrapers'))
sys.path.insert(0, os.path.join(BACKEND_DIR, 'meal-planning'))

from nutrition_scraper import extract_traits_from_html  # noqa: E402
from load_to_db import load_excel_to_database  # noqa: E402
from meal_planner import MealPlanner, get_conflicts, load_dietary_rules, parse_traits  # noqa: E402

RESTRICTIONS_PAGE = os.path.join(
    REPO_DIR, 'Frontend', 'flutter_easyeats', 'lib', 'pages', 'dietary_restrictions_page.dart'
)

# (name, category, traits, calories, protein, fat, carbs)
# traits=None means unknown (scraped before traits were collected)
TEST_DISHES = [
    ('Grilled Chicken', 'Entrees', 'Halal', 220, 35, 6, 0),
    ('Tofu Stir Fry', 'Entrees', 'Soy, Vegan, Vegetarian', 250, 14, 10, 25),
    ('Cheese Pizza', 'Entrees', 'Gluten, Milk, Wheat, Vegetarian', 300, 12, 12, 35),
    ('Shrimp Pasta', 'Entrees', 'Gluten, Shellfish, Wheat', 400, 20, 14, 45),
    ('Peanut Noodles', 'Entrees', 'Gluten, Peanuts, Soy, Wheat, Vegan, Vegetarian', 380, 12, 16, 48),
    ('Scrambled Eggs', 'Entrees', 'Eggs, Milk, Vegetarian', 180, 12, 13, 2),
    ('Kosher Brisket', 'Entrees', 'Kosher', 320, 28, 20, 0),
    ('Mystery Casserole', 'Entrees', None, 350, 18, 15, 30),
    ('Steamed Broccoli', 'Vegetables', 'Vegan, Vegetarian', 50, 4, 0.5, 10),
    ('Garden Salad', 'Salads', 'Vegan, Vegetarian', 40, 2, 0, 8),
    ('Brown Rice', 'Grains', 'Vegan, Vegetarian', 200, 5, 1.5, 42),
    ('Plain Water', 'Beverages', '', 0, 0, 0, 0),
]


def make_test_db(path, dishes=TEST_DISHES, hall='Illinois Street Dining Center (ISR)', meal='Lunch'):
    conn = sqlite3.connect(path)
    conn.execute('''
        CREATE TABLE nutrition_data (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            dining_hall TEXT, service TEXT, date TEXT, meal_type TEXT, category TEXT,
            name TEXT, traits TEXT, serving_size TEXT, calories REAL, total_fat REAL,
            saturated_fat REAL, trans_fat REAL, cholesterol REAL, sodium REAL, potassium REAL,
            total_carbohydrate REAL, dietary_fiber REAL, sugars REAL, protein REAL
        )
    ''')
    for name, category, traits, cal, protein, fat, carbs in dishes:
        conn.execute(
            'INSERT INTO nutrition_data (dining_hall, service, date, meal_type, category, name, traits,'
            ' serving_size, calories, total_fat, total_carbohydrate, dietary_fiber, protein)'
            ' VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
            (hall, 'Main', 'Thursday, October 22, 2026', meal, category, name, traits,
             '1 serving', cal, fat, carbs, 2, protein),
        )
    conn.commit()
    conn.close()


class ScraperTraitParsingTest(unittest.TestCase):
    # Copied from a real eatsmart menu row (October 2026)
    ITEM_HTML = '''Devil's Food Cake Donut
        <span class="pl-2"><img title="Eggs" alt="Eggs image" src="http://eatsmart.housing.illinois.edu/NetNutrition/images/traits/eggs.png"></span>
        <span class="pl-2"><img title="Gluten" alt="Gluten image" src="http://eatsmart.housing.illinois.edu/NetNutrition/images/traits/gluten.png"></span>
        <span class="pl-2"><img title="Milk" alt="Milk image" src="http://eatsmart.housing.illinois.edu/NetNutrition/images/traits/milk.png"></span>
        <span class="pl-2"><img title="Vegetarian" alt="" src="http://eatsmart.housing.illinois.edu/NetNutrition/images/traits/vegetarian24.png"></span>'''

    def test_reads_every_trait_icon(self):
        self.assertEqual(extract_traits_from_html(self.ITEM_HTML), ['Eggs', 'Gluten', 'Milk', 'Vegetarian'])

    def test_no_icons_means_no_traits(self):
        self.assertEqual(extract_traits_from_html('Fresh Banana'), [])
        self.assertEqual(extract_traits_from_html(None), [])

    def test_ignores_images_without_title_and_duplicates(self):
        html = '<img src="x.png"><img title="Soy"><img title="Soy">'
        self.assertEqual(extract_traits_from_html(html), ['Soy'])


class DietaryRulesTest(unittest.TestCase):
    def setUp(self):
        self.rules = load_dietary_rules()

    def test_every_restriction_in_the_app_has_a_rule_or_is_marked_not_checked(self):
        # A name mismatch (e.g. "Gluten Free" vs "Gluten-Free") would silently filter nothing
        with open(RESTRICTIONS_PAGE) as f:
            source = f.read()
        block = re.search(r'_availableRestrictions = \[(.*?)\];', source, re.S).group(1)
        app_restrictions = re.findall(r"'([^']+)'", block)
        with open(os.path.join(BACKEND_DIR, 'dietary_rules.json')) as f:
            not_checked = json.load(f)['_not_checked']
        for restriction in app_restrictions:
            self.assertTrue(restriction in self.rules or restriction in not_checked,
                            f'No rule for "{restriction}"')

    def test_the_ten_label_based_restrictions_have_rules(self):
        for restriction in ['Vegetarian', 'Vegan', 'Gluten-Free', 'Dairy-Free', 'Nut Allergy',
                            'Shellfish Allergy', 'Egg Allergy', 'Soy Allergy', 'Halal', 'Kosher']:
            self.assertIn(restriction, self.rules)

    def test_allergy_excludes_dishes_with_the_allergen(self):
        self.assertEqual(get_conflicts(['Peanuts', 'Soy'], ['Nut Allergy'], self.rules), ['Nut Allergy'])
        self.assertEqual(get_conflicts(['Tree Nuts'], ['Nut Allergy'], self.rules), ['Nut Allergy'])
        self.assertEqual(get_conflicts(['Wheat'], ['Gluten-Free'], self.rules), ['Gluten-Free'])
        self.assertEqual(get_conflicts(['Soy'], ['Nut Allergy', 'Dairy-Free'], self.rules), [])

    def test_diet_requires_its_label(self):
        self.assertEqual(get_conflicts(['Vegetarian'], ['Vegan'], self.rules), ['Vegan'])
        self.assertEqual(get_conflicts(['Vegan'], ['Vegetarian'], self.rules), [])
        self.assertEqual(get_conflicts([], ['Halal', 'Kosher'], self.rules), ['Halal', 'Kosher'])

    def test_unknown_traits_conflict_with_every_restriction(self):
        self.assertEqual(get_conflicts(None, ['Egg Allergy'], self.rules), ['Egg Allergy'])
        self.assertEqual(get_conflicts(None, [], self.rules), [])

    def test_parse_traits(self):
        self.assertEqual(parse_traits('Eggs, Milk'), ['Eggs', 'Milk'])
        self.assertEqual(parse_traits(''), [])
        self.assertIsNone(parse_traits(None))
        self.assertIsNone(parse_traits(float('nan')))


class MealPlannerRestrictionTest(unittest.TestCase):
    RUNS = 100  # The planner is random, so check many plans

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.db = os.path.join(cls.tmp.name, 'test.db')
        make_test_db(cls.db)
        cls.rules = load_dietary_rules()
        cls.traits_by_name = {d[0]: parse_traits(d[2]) for d in TEST_DISHES}

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def plan(self, restrictions, db=None):
        planner = MealPlanner(db_file=db or self.db)
        return planner.create_meal_plan(600, 'ISR', meal_type='Lunch', restrictions=restrictions)

    def test_plans_never_break_a_restriction(self):
        for restrictions in [['Vegan'], ['Vegetarian'], ['Gluten-Free'], ['Nut Allergy'],
                             ['Shellfish Allergy'], ['Egg Allergy'], ['Dairy-Free'], ['Soy Allergy'],
                             ['Halal'], ['Kosher'], ['Vegan', 'Nut Allergy', 'Soy Allergy']]:
            with self.subTest(restrictions=restrictions):
                for _ in range(self.RUNS):
                    plan = self.plan(restrictions)
                    self.assertNotIn('error', plan)
                    self.assertEqual(plan['applied_restrictions'], restrictions)
                    for item in plan['items']:
                        conflicts = get_conflicts(self.traits_by_name[item['name']], restrictions, self.rules)
                        self.assertEqual(conflicts, [], f"{item['name']} breaks {conflicts}")

    def test_unknown_traits_are_never_planned_with_restrictions(self):
        for _ in range(self.RUNS):
            names = [i['name'] for i in self.plan(['Dairy-Free'])['items']]
            self.assertNotIn('Mystery Casserole', names)

    def test_no_restrictions_uses_every_dish(self):
        planner = MealPlanner(db_file=self.db)
        available = planner.filter_available_items('ISR', 'Lunch')
        # Plain Water has 0 calories, so the planner always drops it
        self.assertEqual(len(available), len(TEST_DISHES) - 1)

    def test_unchecked_restrictions_are_not_claimed(self):
        plan = self.plan(['Keto', 'Vegan'])
        self.assertEqual(plan['applied_restrictions'], ['Vegan'])

    def test_impossible_restrictions_return_an_error(self):
        plan = self.plan(['Kosher', 'Vegan'])
        self.assertIn('error', plan)
        self.assertIn('Kosher, Vegan', plan['error'])

    def test_no_protein_dishes_does_not_crash(self):
        # Used to raise IndexError when there was a vegetable but no protein dish
        db = os.path.join(self.tmp.name, 'veg_only.db')
        make_test_db(db, dishes=[d for d in TEST_DISHES if d[1] in ('Vegetables', 'Salads', 'Grains')])
        plan = self.plan([], db=db)
        self.assertNotIn('error', plan)
        self.assertGreater(len(plan['items']), 0)

    def test_dish_without_category_gives_valid_json(self):
        # json.dumps writes NaN for a missing category, which JavaScript's JSON.parse rejects
        db = os.path.join(self.tmp.name, 'no_category.db')
        make_test_db(db, dishes=[('Fresh Pasta', None, 'Gluten, Wheat, Vegan, Vegetarian', 300, 10, 2, 60)])
        plan = self.plan([], db=db)
        self.assertEqual(plan['items'][0]['category'], None)
        json.loads(json.dumps(plan), parse_constant=lambda c: self.fail(f'{c} in JSON'))

    def test_database_without_traits_column(self):
        db = os.path.join(self.tmp.name, 'old.db')
        make_test_db(db)
        conn = sqlite3.connect(db)
        conn.execute('ALTER TABLE nutrition_data DROP COLUMN traits')
        conn.commit()
        conn.close()
        self.assertNotIn('error', self.plan([], db=db))
        self.assertIn('error', self.plan(['Vegan'], db=db))


class LoadToDatabaseTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.tmp.name, 'nutrition.db')

    def tearDown(self):
        self.tmp.cleanup()

    def write_excel(self, rows):
        path = os.path.join(self.tmp.name, 'data.xlsx')
        pd.DataFrame(rows).to_excel(path, index=False)
        return path

    def base_row(self, name, **extra):
        row = {'dining_hall': 'ISR', 'service': 'Main', 'date': 'Thursday, October 22, 2026',
               'meal_type': 'Lunch', 'category': 'Entrees', 'name': name, 'serving_size': '1 each',
               'calories': 100, 'protein': 5, 'total_fat': 2, 'total_carbohydrate': 10}
        row.update(extra)
        return row

    def traits_in_db(self):
        conn = sqlite3.connect(self.db)
        rows = dict(conn.execute('SELECT name, traits FROM nutrition_data').fetchall())
        conn.close()
        return rows

    def test_traits_are_stored_and_no_icons_is_empty_not_null(self):
        excel = self.write_excel([self.base_row('Donut', traits='Eggs, Milk'),
                                  self.base_row('Banana', traits=None)])
        self.assertTrue(load_excel_to_database(excel, self.db))
        self.assertEqual(self.traits_in_db(), {'Donut': 'Eggs, Milk', 'Banana': ''})

    def test_excel_without_traits_column_stores_unknown(self):
        excel = self.write_excel([self.base_row('Donut')])
        self.assertTrue(load_excel_to_database(excel, self.db))
        self.assertEqual(self.traits_in_db(), {'Donut': None})

    def test_adds_traits_column_to_an_old_database(self):
        conn = sqlite3.connect(self.db)
        conn.execute('CREATE TABLE nutrition_data (id INTEGER PRIMARY KEY, dining_hall TEXT NOT NULL,'
                     ' service TEXT NOT NULL, date TEXT NOT NULL, meal_type TEXT NOT NULL, category TEXT,'
                     ' name TEXT NOT NULL, serving_size TEXT, calories REAL, total_fat REAL,'
                     ' saturated_fat REAL, trans_fat REAL, cholesterol REAL, sodium REAL, potassium REAL,'
                     ' total_carbohydrate REAL, dietary_fiber REAL, sugars REAL, protein REAL,'
                     ' scraped_at TIMESTAMP)')
        conn.commit()
        conn.close()
        excel = self.write_excel([self.base_row('Donut', traits='Eggs')])
        self.assertTrue(load_excel_to_database(excel, self.db))
        self.assertEqual(self.traits_in_db(), {'Donut': 'Eggs'})


if __name__ == '__main__':
    unittest.main()
