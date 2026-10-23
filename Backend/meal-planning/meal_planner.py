"""
Meal Planning Algorithm
Generates optimized meal plans based on calorie targets and nutritional goals
"""
import json
import os
import sqlite3
import pandas as pd
import random
import numpy as np
from datetime import datetime
from collections import defaultdict


# Shared with server.js (via dietary.js) so both apply the same rules
RULES_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'dietary_rules.json')


def load_dietary_rules(rules_file=RULES_FILE):
    """Load the restriction -> trait rules (keys starting with '_' are notes, not restrictions)"""
    with open(rules_file) as f:
        rules = json.load(f)
    return {name: rule for name, rule in rules.items() if not name.startswith('_')}


def parse_traits(traits_value):
    """Convert the traits column into a list.

    None/NaN means the traits are unknown (scraped before traits were collected),
    an empty string means the site shows no trait icons for the dish.
    """
    if traits_value is None or (isinstance(traits_value, float) and pd.isna(traits_value)):
        return None
    return [t.strip() for t in str(traits_value).split(',') if t.strip()]


def get_conflicts(traits, restrictions, rules):
    """Return the restrictions a dish does not satisfy.

    A dish with unknown traits can't be verified, so it conflicts with every restriction.
    """
    if not restrictions:
        return []
    if traits is None:
        return list(restrictions)

    conflicts = []
    for restriction in restrictions:
        rule = rules.get(restriction)
        if not rule:
            continue
        if any(t in traits for t in rule.get('exclude', [])):
            conflicts.append(restriction)
        elif 'require_any' in rule and not any(t in traits for t in rule['require_any']):
            conflicts.append(restriction)
    return conflicts


class MealPlanner:
    def __init__(self, db_file='nutrition_data.db', excel_file=None):
        """
        Initialize meal planner

        Args:
            db_file: Path to SQLite database (optional)
            excel_file: Path to Excel file to use instead of database
        """
        self.db_file = db_file
        self.excel_file = excel_file
        self.data = None
        
        # Define nutritional goals (Protein/Fat/Carb splits)
        self.GOALS = {
            'balanced': {'p': 0.30, 'f': 0.30, 'c': 0.40, 'desc': 'Balanced Diet (30/30/40)'},
            'weight_loss': {'p': 0.40, 'f': 0.25, 'c': 0.35, 'desc': 'Weight Loss (High Protein)'},
            'bulking': {'p': 0.30, 'f': 0.20, 'c': 0.50, 'desc': 'Bulking (High Carb/Calorie)'},
            'keto': {'p': 0.25, 'f': 0.70, 'c': 0.05, 'desc': 'Keto (High Fat, Low Carb)'},
        }

    def load_data(self):
        """Load nutrition data from Excel or database"""
        if self.excel_file:
            # print(f"Loading data from Excel: {self.excel_file}")
            self.data = pd.read_excel(self.excel_file)
        else:
            # print(f"Loading data from database: {self.db_file}")
            conn = sqlite3.connect(self.db_file)
            self.data = pd.read_sql_query("SELECT * FROM nutrition_data", conn)
            conn.close()

    def get_current_meal_type(self):
        """Automatically determine meal type based on current time"""
        current_hour = datetime.now().hour

        if 6 <= current_hour < 10:
            return "Breakfast"
        elif 10 <= current_hour < 15:
            return "Lunch"
        elif 15 <= current_hour < 21:
            return "Dinner"
        else:
            if current_hour >= 21 or current_hour < 6:
                return "Breakfast"
            return "Lunch"

    def filter_available_items(self, dining_hall, meal_type, date=None, restrictions=None):
        """Filter items available for specific dining hall and meal"""
        if self.data is None:
            self.load_data()

        # Older databases have no traits column; treat every dish as unknown
        if 'traits' not in self.data.columns:
            self.data['traits'] = None

        # Filter by dining hall (partial match)
        filtered = self.data[self.data['dining_hall'].str.contains(dining_hall, case=False, na=False)]

        # Filter by meal type
        filtered = filtered[filtered['meal_type'] == meal_type]

        # Filter by date if provided
        if date:
            filtered = filtered[filtered['date'].str.contains(date, case=False, na=False)]

        # Remove items with missing critical nutrition data
        filtered = filtered[
            (filtered['calories'].notna()) &
            (filtered['calories'] > 0) &
            (filtered['protein'].notna()) &
            (filtered['total_fat'].notna())
        ]

        # Keep only dishes that satisfy every dietary restriction
        if restrictions:
            rules = load_dietary_rules()
            fits = filtered['traits'].apply(
                lambda t: not get_conflicts(parse_traits(t), restrictions, rules)
            )
            filtered = filtered[fits]

        return filtered.copy()

    def categorize_items(self, items_df):
        """Categorize items into food groups"""
        categories = {
            'protein': items_df[items_df['category'].str.contains(
                'entree|protein|chicken|beef|fish|pork|turkey|tofu|egg',
                case=False, na=False
            )],
            'carbs': items_df[items_df['category'].str.contains(
                'grain|rice|pasta|bread|potato|starch|cereal',
                case=False, na=False
            )],
            'vegetables': items_df[items_df['category'].str.contains(
                'vegetable|veggie|salad|greens',
                case=False, na=False
            )],
            'other': items_df  # All items as fallback
        }

        # Also categorize by name if category is missing
        for idx, row in items_df.iterrows():
            name_lower = str(row['name']).lower()

            if any(word in name_lower for word in ['chicken', 'beef', 'pork', 'fish', 'salmon',
                                                     'turkey', 'egg', 'tofu', 'bean', 'lentil']):
                if idx not in categories['protein'].index:
                    categories['protein'] = pd.concat([categories['protein'], items_df.loc[[idx]]])

            if any(word in name_lower for word in ['rice', 'pasta', 'bread', 'potato', 'noodle',
                                                     'tortilla', 'quinoa', 'oat']):
                if idx not in categories['carbs'].index:
                    categories['carbs'] = pd.concat([categories['carbs'], items_df.loc[[idx]]])

            if any(word in name_lower for word in ['broccoli', 'carrot', 'spinach', 'lettuce',
                                                     'tomato', 'pepper', 'green', 'salad', 'veggie']):
                if idx not in categories['vegetables'].index:
                    categories['vegetables'] = pd.concat([categories['vegetables'], items_df.loc[[idx]]])

        return categories

    def score_item(self, item, goal_config):
        """
        Score an item based on nutritional value and current goal
        """
        score = 0.0
        calories = float(item['calories'])
        protein = float(item['protein'])
        fat = float(item['total_fat'])
        carbs = float(item['total_carbohydrate'])
        fiber = float(item['dietary_fiber']) if pd.notna(item['dietary_fiber']) else 0

        if calories <= 0: return 0

        # Calculate density (per 100 cal)
        p_density = (protein * 4) / calories
        f_density = (fat * 9) / calories
        c_density = (carbs * 4) / calories

        # Score based on proximity to goal ratios
        # We reward items that help us hit the target ratio
        
        # Protein Score
        if p_density >= goal_config['p']:
            score += 30  # Excellent protein source
        elif p_density >= goal_config['p'] * 0.5:
            score += 15  # Decent protein source

        # Fat Score
        # For Keto, we want high fat. For others, we usually want moderate fat.
        if goal_config['f'] > 0.5: # Keto
            if f_density >= 0.5: score += 20
        else: # Normal
            if f_density <= 0.35: score += 20 # Low saturated fat usually preferred
            
        # Carb Score
        if goal_config['c'] < 0.1: # Keto/Low Carb
            if c_density < 0.1: score += 30 # Low carb is good
            elif c_density > 0.3: score -= 20 # High carb is bad
        else:
            if 0.3 <= c_density <= 0.6: score += 10 # Moderate carbs good for energy

        # Fiber is always good
        score += min(fiber * 3, 15)

        return score

    def generate_random_meal(self, categories, target_calories, goal_config, max_items=5):
        """
        Generate a single valid random meal combination
        """
        selected_items = []
        current_cals = 0
        
        # Ensure we get a main protein
        if not categories['protein'].empty:
            main = categories['protein'].sample(n=1).iloc[0]
            selected_items.append(main)
            current_cals += main['calories']
            
        # Ensure we get a vegetable
        if not categories['vegetables'].empty:
            veg = categories['vegetables'].sample(n=1).iloc[0]
            # Avoid duplicates (there may be no protein item to compare against)
            if not any(s['name'] == veg['name'] for s in selected_items):
                selected_items.append(veg)
                current_cals += veg['calories']
                
        # Fill rest with random items from any category until close to target
        attempts = 0
        while len(selected_items) < max_items and attempts < 10:
            attempts += 1
            
            # Pick a random category based on what we might need
            # Simple logic: just pick random for now
            cat_name = random.choice(['protein', 'carbs', 'vegetables', 'other'])
            if categories[cat_name].empty: continue
            
            item = categories[cat_name].sample(n=1).iloc[0]
            
            # Skip duplicates
            if any(s['name'] == item['name'] for s in selected_items):
                continue
                
            # Check if it fits
            if current_cals + item['calories'] > target_calories * 1.2:
                continue
                
            selected_items.append(item)
            current_cals += item['calories']
            
            if current_cals >= target_calories * 0.9:
                break
                
        return selected_items

    def is_discrete_item(self, name):
        """Check if item should be counted in discrete units (0.5, 1.0, etc.)"""
        name_lower = str(name).lower()
        discrete_keywords = [
            'bun', 'bread', 'roll', 'slice', 'cookie', 'egg', 'patty', 
            'burger', 'sandwich', 'apple', 'banana', 'orange', 'pear',
            'muffin', 'bagel', 'toast', 'wrap', 'taco', 'burrito', 'pizza',
            'donut', 'pancake', 'waffle', 'sausage'
        ]
        return any(keyword in name_lower for keyword in discrete_keywords)

    def optimize_servings(self, items, target_calories):
        """
        Adjust servings to hit calorie target exactly, respecting discrete items
        """
        if not items: return items
        
        total_cals_initial = sum(item['calories'] for item in items)
        if total_cals_initial == 0: return items
        
        # Initial global scale
        global_scale = target_calories / total_cals_initial
        global_scale = max(0.5, min(global_scale, 2.0))
        
        discrete_items = []
        continuous_items = []
        
        current_cals = 0
        
        # Step 1: Process discrete items first
        for item in items:
            if self.is_discrete_item(item['name']):
                # Scale and round to nearest 0.5
                ideal_servings = item['servings'] * global_scale
                rounded_servings = round(ideal_servings * 2) / 2
                rounded_servings = max(0.5, rounded_servings) # Min 0.5
                
                new_item = item.copy()
                new_item['servings'] = rounded_servings
                new_item['calories'] = round(item['calories'] / item['servings'] * rounded_servings, 1)
                new_item['protein'] = round(item['protein'] / item['servings'] * rounded_servings, 1)
                new_item['total_fat'] = round(item['total_fat'] / item['servings'] * rounded_servings, 1)
                new_item['total_carbohydrate'] = round(item['total_carbohydrate'] / item['servings'] * rounded_servings, 1)
                
                # Handle fiber safely
                fiber_val = item.get('dietary_fiber', 0)
                if pd.isna(fiber_val): fiber_val = 0
                new_item['dietary_fiber'] = round(float(fiber_val) / item['servings'] * rounded_servings, 1)
                
                discrete_items.append(new_item)
                current_cals += new_item['calories']
            else:
                continuous_items.append(item)

        # Step 2: Adjust continuous items to fill the gap
        remaining_cals = target_calories - current_cals
        continuous_initial_cals = sum(i['calories'] for i in continuous_items)
        
        final_items = discrete_items.copy()
        
        if continuous_items:
            # If we have continuous items, scale them to fit remaining calories
            # But don't let them go negative or too crazy
            if continuous_initial_cals > 0 and remaining_cals > 0:
                cont_scale = remaining_cals / continuous_initial_cals
                # Clamp scale to avoid huge portions just to fill calories
                cont_scale = max(0.2, min(cont_scale, 3.0))
            else:
                cont_scale = global_scale # Fallback if math gets weird
                
            for item in continuous_items:
                new_item = item.copy()
                new_item['servings'] = round(item['servings'] * cont_scale, 2)
                new_item['calories'] = round(item['calories'] * cont_scale, 1)
                new_item['protein'] = round(item['protein'] * cont_scale, 1)
                new_item['total_fat'] = round(item['total_fat'] * cont_scale, 1)
                new_item['total_carbohydrate'] = round(item['total_carbohydrate'] * cont_scale, 1)
                
                fiber_val = item.get('dietary_fiber', 0)
                if pd.isna(fiber_val): fiber_val = 0
                new_item['dietary_fiber'] = round(float(fiber_val) * cont_scale, 1)
                
                final_items.append(new_item)
        else:
            # If no continuous items, we just have to live with the discrete rounding
            # Maybe add the original continuous items back scaled globally if logic failed?
            # But here continuous_items is empty, so we are done.
            pass
            
        return final_items

    def evaluate_meal(self, items, target_calories, goal_config):
        """
        Calculate a total score for a complete meal
        """
        total_cals = sum(item['calories'] for item in items)
        total_p = sum(item['protein'] for item in items)
        total_f = sum(item['total_fat'] for item in items)
        total_c = sum(item['total_carbohydrate'] for item in items)
        
        if total_cals == 0: return -1000
        
        # 1. Calorie Score (how close to target)
        cal_diff_percent = abs(total_cals - target_calories) / target_calories
        cal_score = max(0, 100 - (cal_diff_percent * 200)) # 100 pts if exact, 0 if >50% off
        
        # 2. Macro Balance Score
        p_ratio = (total_p * 4) / total_cals
        f_ratio = (total_f * 9) / total_cals
        c_ratio = (total_c * 4) / total_cals
        
        # Euclidean distance from goal vector
        dist = np.sqrt(
            (p_ratio - goal_config['p'])**2 +
            (f_ratio - goal_config['f'])**2 +
            (c_ratio - goal_config['c'])**2
        )
        macro_score = max(0, 100 - (dist * 200))
        
        # 3. Diversity Score (bonus for using multiple categories)
        cats = set()
        for item in items:
            # We need to re-infer category or pass it through. 
            # For simplicity, we assume the item dict has 'category'
            cats.add(str(item['category']))
        div_score = len(cats) * 10
        
        return (cal_score * 0.4) + (macro_score * 0.5) + (div_score * 0.1)

    def create_meal_plan(self, target_calories, dining_hall, meal_type=None, goal='balanced', restrictions=None):
        """
        Create an optimized meal plan using Randomized Search
        """
        if meal_type is None:
            meal_type = self.get_current_meal_type()

        goal_config = self.GOALS.get(goal, self.GOALS['balanced'])
        # Only restrictions the dining labels can check (e.g. not Keto)
        rules = load_dietary_rules()
        restrictions = [r for r in (restrictions or []) if r in rules]

        # Get available items
        available_items = self.filter_available_items(dining_hall, meal_type, restrictions=restrictions)

        if len(available_items) == 0:
            if restrictions:
                return {'error': f'No items found for {dining_hall} - {meal_type} that fit: {", ".join(restrictions)}'}
            return {'error': f'No items found for {dining_hall} - {meal_type}'}

        # Categorize
        categories = self.categorize_items(available_items)
        
        best_meal = None
        best_score = -float('inf')
        
        # Randomized Search (Monte Carlo)
        # Generate 50 random valid meals, score them, pick best
        for _ in range(50):
            # 1. Generate random items
            items_df = self.generate_random_meal(categories, target_calories, goal_config)
            
            # 2. Convert to list of dicts for processing
            items_list = []
            for row in items_df:
                item_dict = row.to_dict()
                item_dict['servings'] = 1.0 # Initialize servings
                items_list.append(item_dict)
            
            # 3. Optimize servings to hit calorie target
            optimized_items = self.optimize_servings(items_list, target_calories)
            
            # 4. Score
            score = self.evaluate_meal(optimized_items, target_calories, goal_config)
            
            if score > best_score:
                best_score = score
                best_meal = optimized_items

        # Final formatting
        total_calories = sum(i['calories'] for i in best_meal)
        total_protein = sum(i['protein'] for i in best_meal)
        total_fat = sum(i['total_fat'] for i in best_meal)
        total_carbs = sum(i['total_carbohydrate'] for i in best_meal)
        
        # Calculate percentages
        fat_percent = (total_fat * 9 / total_calories * 100) if total_calories > 0 else 0
        protein_percent = (total_protein * 4 / total_calories * 100) if total_calories > 0 else 0
        carb_percent = (total_carbs * 4 / total_calories * 100) if total_calories > 0 else 0

        # Clean up items for JSON output
        final_items_clean = []
        for item in best_meal:
            final_items_clean.append({
                'name': item['name'],
                # A missing category is NaN, which json.dumps writes as invalid JSON
                'category': item['category'] if pd.notna(item['category']) else None,
                'servings': item['servings'],
                'calories': item['calories'],
                'protein': item['protein'],
                'fat': item['total_fat'],
                'carbs': item['total_carbohydrate'],
                'traits': parse_traits(item.get('traits')),
                'score': 0 # Legacy field
            })

        return {
            'dining_hall': dining_hall,
            'meal_type': meal_type,
            'target_calories': target_calories,
            'goal': goal_config['desc'],
            'applied_restrictions': restrictions,
            'actual_calories': round(total_calories, 1),
            'items': final_items_clean,
            'totals': {
                'calories': round(total_calories, 1),
                'protein': round(total_protein, 1),
                'fat': round(total_fat, 1),
                'carbs': round(total_carbs, 1),
                'fat_percent': round(fat_percent, 1),
                'protein_percent': round(protein_percent, 1),
                'carb_percent': round(carb_percent, 1)
            },
            'meets_target': abs(total_calories - target_calories) < (target_calories * 0.1)
        }

if __name__ == "__main__":
    import argparse
    import json
    import os
    import sys

    # Default paths
    current_dir = os.path.dirname(os.path.abspath(__file__))
    backend_dir = os.path.dirname(current_dir)
    default_db = os.path.join(backend_dir, 'data', 'nutrition_data.db')
    
    if not os.path.exists(default_db):
        default_db = 'nutrition_data.db'

    parser = argparse.ArgumentParser()
    parser.add_argument('--calories', type=int, default=600)
    parser.add_argument('--hall', type=str, default='ISR')
    parser.add_argument('--meal', type=str)
    parser.add_argument('--goal', type=str, default='balanced', choices=['balanced', 'weight_loss', 'bulking', 'keto'])
    parser.add_argument('--db', type=str, default=default_db)
    parser.add_argument('--json', action='store_true')
    parser.add_argument('--restrictions', type=str, default='',
                        help='Comma-separated dietary restrictions, e.g. "Vegan,Nut Allergy"')

    args = parser.parse_args()
    restrictions = [r.strip() for r in args.restrictions.split(',') if r.strip()]

    planner = MealPlanner(db_file=args.db)
    meal_plan = planner.create_meal_plan(
        target_calories=args.calories,
        dining_hall=args.hall,
        meal_type=args.meal,
        goal=args.goal,
        restrictions=restrictions
    )

    if args.json:
        print(json.dumps(meal_plan))
    else:
        print(json.dumps(meal_plan, indent=2))
