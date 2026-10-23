import 'package:flutter_test/flutter_test.dart';
import 'package:easyeats/models/food_item.dart';

void main() {
  group('FoodItem dietary info', () {
    test('reads traits and conflicts from the API', () {
      final food = FoodItem.fromJson({
        'name': 'Cheese Pizza',
        'calories': 300,
        'protein': 12,
        'total_fat': 12,
        'total_carbohydrate': 35,
        'traits': ['Gluten', 'Milk', 'Wheat', 'Vegetarian'],
        'conflicts': ['Vegan'],
      });

      expect(food.traits, ['Gluten', 'Milk', 'Wheat', 'Vegetarian']);
      expect(food.conflicts, ['Vegan']);
      expect(food.dietLabels, ['Vegetarian']);
      expect(food.containsLabels, ['Gluten', 'Milk', 'Wheat']);
    });

    test('handles foods from before traits existed', () {
      final food = FoodItem.fromJson({
        'name': 'Brown Rice',
        'calories': 200,
        'protein': 5,
        'total_fat': 1.5,
        'total_carbohydrate': 42,
      });

      expect(food.traits, isNull);
      expect(food.conflicts, isEmpty);
      expect(food.dietLabels, isEmpty);
      expect(food.containsLabels, isEmpty);
    });

    test('keeps traits when logged as part of a meal', () {
      final food = FoodItem(
        name: 'Tofu Stir Fry',
        calories: 250,
        protein: 14,
        totalFat: 10,
        totalCarbohydrate: 25,
        traits: ['Soy', 'Vegan'],
      );

      expect(food.toJson()['traits'], ['Soy', 'Vegan']);
      expect(FoodItem.fromJson(food.toJson()).traits, ['Soy', 'Vegan']);
    });
  });
}
