# Backend API Handbook

This guide documents the backend API for the EasyEats application and provides instructions for integrating it with the Flutter frontend.

## 🚀 Getting Started

### Base URL
The backend server runs on port **3000** by default.

- **Localhost (Web/iOS Simulator)**: `http://localhost:3000`
- **Android Emulator**: `http://10.0.2.2:3000` (Android emulators use this special IP to access the host machine's localhost)
- **Physical Device**: You need to use your computer's local IP address (e.g., `http://192.168.1.5:3000`).

### Prerequisites
Ensure the backend server is running before making requests:
```bash
cd Backend
npm start
```

---

## 📡 API Endpoints

### 1. Health Check
Verify that the server is running and reachable.

- **Endpoint**: `/health`
- **Method**: `GET`
- **Response**:
  ```json
  {
    "status": "ok",
    "timestamp": "2024-11-25T20:30:00.000Z"
  }
  ```

### 2. Generate Meal Plan
Generates an optimized meal plan based on nutritional goals and location.

- **Endpoint**: `/api/meal-plan`
- **Method**: `GET`
- **Query Parameters**:
  - `calories` (Required): Target calorie count (integer). Example: `600`.
  - `dining_hall` (Required): Name of the dining hall. Example: `ISR`, `Ikenberry`.
  - `meal_type` (Optional): `Breakfast`, `Lunch`, or `Dinner`. If omitted, it defaults based on the current time.
  - `user_id` (Optional): Plan only with dishes that fit this user's dietary restrictions. The response's `applied_restrictions` lists the ones that were checked, and each item has a `traits` list (e.g. `["Milk", "Vegetarian"]`). See [Dietary restrictions](RUN.md#dietary-restrictions).

- **Example Request**:
  ```
  GET /api/meal-plan?calories=700&dining_hall=ISR&meal_type=Lunch
  ```

- **Example Response (Success)**:
  ```json
  {
    "dining_hall": "ISR",
    "meal_type": "Lunch",
    "target_calories": 700,
    "calorie_range": "630-770",
    "actual_calories": 685.5,
    "items": [
      {
        "name": "Grilled Chicken Breast",
        "category": "Protein",
        "servings": 1.0,
        "calories": 180.0,
        "protein": 35.0,
        "fat": 4.0,
        "carbs": 0.0,
        "score": 45.5
      },
      {
        "name": "Steamed Broccoli",
        "category": "Vegetables",
        "servings": 1.5,
        "calories": 45.0,
        "protein": 4.0,
        "fat": 0.5,
        "carbs": 8.0,
        "score": 30.0
      }
    ],
    "totals": {
      "calories": 685.5,
      "protein": 65.0,
      "fat": 22.0,
      "carbs": 55.0,
      "fat_percent": 28.9,
      "protein_percent": 37.9,
      "carb_percent": 32.1
    },
    "meets_target": true,
    "within_fat_limit": true
  }
  ```

- **Example Response (Error)**:
  ```json
  {
    "error": "Missing required parameters: calories and dining_hall are required"
  }
  ```

---

## 📱 Flutter Integration Guide

### 1. Add Dependency
Add the `http` package to your `pubspec.yaml`:
```yaml
dependencies:
  http: ^1.2.0
```

### 2. Create Meal Service
Create a file `lib/services/meal_service.dart`:

```dart
import 'dart:convert';
import 'dart:io';
import 'package:http/http.dart' as http;
import 'package:flutter/foundation.dart';

class MealService {
  // Use 10.0.2.2 for Android Emulator, localhost for iOS/Web
  static String get baseUrl {
    if (kIsWeb) return 'http://localhost:3000';
    if (Platform.isAndroid) return 'http://10.0.2.2:3000';
    return 'http://localhost:3000';
  }

  Future<Map<String, dynamic>> getMealPlan({
    required int calories,
    required String diningHall,
    String? mealType,
  }) async {
    final queryParams = {
      'calories': calories.toString(),
      'dining_hall': diningHall,
      if (mealType != null) 'meal_type': mealType,
    };

    final uri = Uri.parse('$baseUrl/api/meal-plan').replace(queryParameters: queryParams);

    try {
      final response = await http.get(uri);

      if (response.statusCode == 200) {
        return json.decode(response.body);
      } else {
        throw Exception('Failed to load meal plan: ${response.body}');
      }
    } catch (e) {
      throw Exception('Error connecting to server: $e');
    }
  }
}
```

### 3. Usage in UI
Example of how to call this service in a Widget:

```dart
void _fetchMealPlan() async {
  final mealService = MealService();
  try {
    final plan = await mealService.getMealPlan(
      calories: 600,
      diningHall: 'ISR',
      mealType: 'Dinner'
    );
    
    print('Got meal plan with ${plan['items'].length} items');
    // Update state with setState(() { ... })
  } catch (e) {
    print('Error: $e');
    // Show error snackbar
  }
}
```

---

## 🛠 Troubleshooting

### "Connection Refused"
- **Cause**: The backend server is not running, or you are using the wrong URL (e.g., using `localhost` on Android).
- **Fix**: 
  1. Ensure `npm start` is running in the `Backend` folder.
  2. Use `10.0.2.2` if on Android Emulator.

### "Missing required parameters"
- **Cause**: You forgot to send `calories` or `dining_hall`.
- **Fix**: Check your query parameters in the URL.

### "Failed to generate meal plan" (500 Error)
- **Cause**: The Python script failed to run or returned invalid data.
- **Fix**: Check the terminal where `npm start` is running. It will show the Python error output. Common issues include missing Python libraries (`pandas`, `sqlite3`) or database file not found.
