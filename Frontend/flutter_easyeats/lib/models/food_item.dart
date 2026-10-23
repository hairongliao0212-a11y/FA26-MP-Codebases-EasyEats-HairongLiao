class FoodItem {
  // Traits from eatsmart that describe a diet the dish fits, rather than an ingredient it contains
  static const Set<String> dietTraitNames = {
    'Vegan',
    'Vegetarian',
    'Halal',
    'Kosher',
    'Jain',
    'Local',
    'Sustainable Seafood',
  };

  final String name;
  final String? category;
  final String? servingSize;
  final double calories;
  final double protein;
  final double totalFat;
  final double totalCarbohydrate;
  final double? dietaryFiber;
  final double? sugars;
  final double? sodium;
  // Allergen and diet traits, e.g. ['Milk', 'Vegetarian']; null if unknown
  final List<String>? traits;
  // The user's dietary restrictions this dish doesn't fit (empty if it fits all)
  final List<String> conflicts;

  FoodItem({
    required this.name,
    this.category,
    this.servingSize,
    required this.calories,
    required this.protein,
    required this.totalFat,
    required this.totalCarbohydrate,
    this.dietaryFiber,
    this.sugars,
    this.sodium,
    this.traits,
    this.conflicts = const [],
  });

  // Diet labels such as Vegan or Halal
  List<String> get dietLabels =>
      (traits ?? []).where((t) => dietTraitNames.contains(t)).toList();

  // Allergens and other ingredients such as Milk or Wheat
  List<String> get containsLabels =>
      (traits ?? []).where((t) => !dietTraitNames.contains(t)).toList();

  factory FoodItem.fromJson(Map<String, dynamic> json) {
    return FoodItem(
      name: json['name'] ?? '',
      category: json['category'],
      servingSize: json['serving_size'],
      calories: (json['calories'] ?? 0).toDouble(),
      protein: (json['protein'] ?? 0).toDouble(),
      totalFat: (json['total_fat'] ?? 0).toDouble(),
      totalCarbohydrate: (json['total_carbohydrate'] ?? 0).toDouble(),
      dietaryFiber: json['dietary_fiber'] != null ? (json['dietary_fiber']).toDouble() : null,
      sugars: json['sugars'] != null ? (json['sugars']).toDouble() : null,
      sodium: json['sodium'] != null ? (json['sodium']).toDouble() : null,
      traits: json['traits'] != null ? List<String>.from(json['traits']) : null,
      conflicts: List<String>.from(json['conflicts'] ?? []),
    );
  }

  Map<String, dynamic> toJson() {
    return {
      'name': name,
      'category': category,
      'serving_size': servingSize,
      'calories': calories,
      'protein': protein,
      'total_fat': totalFat,
      'total_carbohydrate': totalCarbohydrate,
      'dietary_fiber': dietaryFiber,
      'sugars': sugars,
      'sodium': sodium,
      'traits': traits,
    };
  }
}
