const express = require('express');
const cors = require('cors');
const { spawn } = require('child_process');
const path = require('path');
const auth = require('./auth');
const dietary = require('./dietary');
const sqlite3 = require('sqlite3').verbose();
const fs = require('fs');

const app = express();
const PORT = process.env.PORT || 3000;

// Database connection (NUTRITION_DB lets tests point at a small test database)
const dbPath = process.env.NUTRITION_DB || path.join(__dirname, 'data', 'nutrition_data.db');
const db = new sqlite3.Database(dbPath);

// Middleware
app.use(cors());
app.use(express.json());

// API Endpoint
app.get('/api/meal-plan', (req, res) => {
    const { calories, dining_hall, meal_type } = req.query;

    // Validate required parameters
    if (!calories || !dining_hall) {
        return res.status(400).json({
            error: 'Missing required parameters: calories and dining_hall are required'
        });
    }

    // Path to Python script
    const scriptPath = path.join(__dirname, 'meal-planning', 'meal_planner.py');

    // Build arguments
    const args = [
        scriptPath,
        '--calories', calories,
        '--hall', dining_hall,
        '--json' // Force JSON output
    ];

    if (meal_type) {
        args.push('--meal', meal_type);
    }

    if (req.query.goal) {
        args.push('--goal', req.query.goal);
    }

    // Use the same database as the rest of the API
    args.push('--db', dbPath);

    // Pass user_id to plan around that user's dietary restrictions
    if (!req.query.user_id) {
        return runMealPlanner(args, res);
    }

    auth.getUserProfile(parseInt(req.query.user_id), (err, user) => {
        if (err) {
            return res.status(404).json(err);
        }
        const restrictions = dietary.supportedRestrictions(user.dietary_restrictions);
        if (restrictions.length > 0) {
            args.push('--restrictions', restrictions.join(','));
        }
        runMealPlanner(args, res);
    });
});

// Run meal_planner.py with the given arguments and send its JSON output as the response
function runMealPlanner(args, res) {
    // Spawn Python process
    // Note: Using 'python3' - make sure it's in the path
    const pythonProcess = spawn('python3', args);

    let dataString = '';
    let errorString = '';

    // Collect data from stdout
    pythonProcess.stdout.on('data', (data) => {
        dataString += data.toString();
    });

    // Collect errors from stderr
    pythonProcess.stderr.on('data', (data) => {
        errorString += data.toString();
    });

    // Handle process close
    pythonProcess.on('close', (code) => {
        if (code !== 0) {
            console.error(`Python script exited with code ${code}`);
            console.error(`Error: ${errorString}`);
            return res.status(500).json({
                error: 'Failed to generate meal plan',
                details: errorString
            });
        }

        try {
            // Parse JSON output from Python script
            // The script might print other things (like warnings) to stdout if not careful
            // But our modified script should only print JSON when --json is used
            // We'll try to find the JSON object in the output if there's extra noise

            // Simple attempt: parse the whole string
            const mealPlan = JSON.parse(dataString);
            res.json(mealPlan);
        } catch (e) {
            console.error('Failed to parse JSON output:', e);
            console.error('Raw output:', dataString);

            // Fallback: try to find the last JSON object in the output
            try {
                const lines = dataString.trim().split('\n');
                const lastLine = lines[lines.length - 1];
                const mealPlan = JSON.parse(lastLine);
                res.json(mealPlan);
            } catch (e2) {
                res.status(500).json({
                    error: 'Invalid response from meal planner',
                    raw_output: dataString
                });
            }
        }
    });
}

// Authentication endpoints
app.post('/api/auth/register', (req, res) => {
    const { email, password } = req.body;

    if (!email || !password) {
        return res.status(400).json({ error: 'Email and password are required' });
    }

    // Basic email validation
    const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    if (!emailRegex.test(email)) {
        return res.status(400).json({ error: 'Invalid email format' });
    }

    // Password length check
    if (password.length < 6) {
        return res.status(400).json({ error: 'Password must be at least 6 characters' });
    }

    auth.registerUser(email, password, (err, result) => {
        if (err) {
            return res.status(400).json(err);
        }
        res.status(201).json(result);
    });
});

app.post('/api/auth/login', (req, res) => {
    const { email, password } = req.body;

    if (!email || !password) {
        return res.status(400).json({ error: 'Email and password are required' });
    }

    auth.loginUser(email, password, (err, result) => {
        if (err) {
            return res.status(401).json(err);
        }
        res.json(result);
    });
});

app.put('/api/user/:userId/profile', (req, res) => {
    const userId = parseInt(req.params.userId);
    const profileData = req.body;

    auth.updateUserProfile(userId, profileData, (err, result) => {
        if (err) {
            return res.status(400).json(err);
        }
        res.json(result);
    });
});

app.get('/api/user/:userId/profile', (req, res) => {
    const userId = parseInt(req.params.userId);

    auth.getUserProfile(userId, (err, result) => {
        if (err) {
            return res.status(404).json(err);
        }
        res.json(result);
    });
});

app.post('/api/user/:userId/change-password', (req, res) => {
    const userId = parseInt(req.params.userId);
    const { oldPassword, newPassword } = req.body;

    if (!oldPassword || !newPassword) {
        return res.status(400).json({ error: 'Old and new passwords are required' });
    }

    if (newPassword.length < 6) {
        return res.status(400).json({ error: 'New password must be at least 6 characters' });
    }

    auth.changePassword(userId, oldPassword, newPassword, (err, result) => {
        if (err) {
            return res.status(400).json(err);
        }
        res.json(result);
    });
});

app.post('/api/user/:userId/favorites', (req, res) => {
    const userId = parseInt(req.params.userId);
    const { foodItem } = req.body;

    if (!foodItem) {
        return res.status(400).json({ error: 'Food item is required' });
    }

    auth.addFavorite(userId, foodItem, (err, result) => {
        if (err) {
            return res.status(400).json(err);
        }
        res.json(result);
    });
});

app.delete('/api/user/:userId/favorites/:index', (req, res) => {
    const userId = parseInt(req.params.userId);
    const index = parseInt(req.params.index);

    auth.removeFavorite(userId, index, (err, result) => {
        if (err) {
            return res.status(400).json(err);
        }
        res.json(result);
    });
});

// ============ NUTRITION DATA ENDPOINTS ============

// Get all available dining halls
app.get('/api/dining-halls', (req, res) => {
    const query = `SELECT DISTINCT dining_hall FROM nutrition_data ORDER BY dining_hall`;

    db.all(query, [], (err, rows) => {
        if (err) {
            return res.status(500).json({ error: 'Database error', details: err.message });
        }
        const halls = rows.map(row => row.dining_hall);
        res.json({ dining_halls: halls });
    });
});

// Attach traits as a list and, when restrictions are given, the ones each food breaks
function withDietaryInfo(food, restrictions) {
    const traits = dietary.parseTraits(food.traits);
    return {
        ...food,
        traits,
        conflicts: dietary.getConflicts(traits, restrictions)
    };
}

// Get foods for a specific dining hall and meal type
// Pass user_id to have each food marked with the user's restrictions it conflicts with
app.get('/api/dining-halls/:hall/foods', (req, res) => {
    const { hall } = req.params;
    const { meal_type, date, user_id } = req.query;

    let query = `
        SELECT DISTINCT name, category, serving_size, calories, protein,
               total_fat, total_carbohydrate, dietary_fiber, sugars, sodium, traits
        FROM nutrition_data
        WHERE dining_hall LIKE ?
    `;
    const params = [`%${hall}%`];

    if (meal_type) {
        query += ` AND meal_type = ?`;
        params.push(meal_type);
    }

    if (date) {
        query += ` AND date = ?`;
        params.push(date);
    }

    query += ` GROUP BY name ORDER BY category, name`;

    db.all(query, params, (err, rows) => {
        if (err) {
            return res.status(500).json({ error: 'Database error', details: err.message });
        }

        const respond = (restrictions) => {
            const foods = rows.map(row => withDietaryInfo(row, restrictions));
            res.json({ foods, count: foods.length, applied_restrictions: restrictions });
        };

        if (!user_id) {
            return respond([]);
        }

        auth.getUserProfile(parseInt(user_id), (err, user) => {
            if (err) {
                return res.status(404).json(err);
            }
            respond(dietary.supportedRestrictions(user.dietary_restrictions));
        });
    });
});

// Get recommended foods for user based on goals
app.get('/api/recommendations/:userId', (req, res) => {
    const userId = parseInt(req.params.userId);
    const { dining_hall, meal_type } = req.query;

    if (!dining_hall) {
        return res.status(400).json({ error: 'dining_hall is required' });
    }

    // Get user profile to understand their goals
    auth.getUserProfile(userId, (err, user) => {
        if (err) {
            return res.status(404).json(err);
        }

        const targetCaloriesPerMeal = Math.floor((user.calories || 2000) / 3);
        const restrictions = dietary.supportedRestrictions(user.dietary_restrictions);

        // Get foods from the dining hall
        let query = `
            SELECT DISTINCT name, category, serving_size, calories, protein,
                   total_fat, total_carbohydrate, dietary_fiber, sugars, sodium, traits,
                   (protein * 4.0 / NULLIF(calories, 0)) as protein_ratio,
                   (total_fat * 9.0 / NULLIF(calories, 0)) as fat_ratio
            FROM nutrition_data
            WHERE dining_hall LIKE ?
            AND calories > 0
        `;
        const params = [`%${dining_hall}%`];

        if (meal_type) {
            query += ` AND meal_type = ?`;
            params.push(meal_type);
        }

        // Score foods based on nutrition
        // The top 20 are taken after dietary filtering, so no LIMIT here
        query += `
            GROUP BY name
            ORDER BY
                (protein * 4.0 / NULLIF(calories, 0)) DESC,
                (total_fat * 9.0 / NULLIF(calories, 0)) ASC,
                dietary_fiber DESC
        `;

        db.all(query, params, (err, rows) => {
            if (err) {
                return res.status(500).json({ error: 'Database error', details: err.message });
            }

            // Only recommend foods that satisfy every one of the user's restrictions
            const foods = rows
                .map(row => withDietaryInfo(row, restrictions))
                .filter(food => food.conflicts.length === 0)
                .slice(0, 20);

            res.json({
                recommendations: foods,
                user_target_calories: targetCaloriesPerMeal,
                goal: user.goal,
                applied_restrictions: restrictions,
                count: foods.length
            });
        });
    });
});

// ============ MEAL TRACKING ENDPOINTS ============

// Initialize meal tracking database
const mealTrackingDbPath = path.join(__dirname, 'data', 'meal_tracking.json');

// Helper function to read meal tracking data
function readMealTracking() {
    try {
        if (fs.existsSync(mealTrackingDbPath)) {
            const data = fs.readFileSync(mealTrackingDbPath, 'utf8');
            return JSON.parse(data);
        }
    } catch (e) {
        console.error('Error reading meal tracking data:', e);
    }
    return { meals: [] };
}

// Helper function to write meal tracking data
function writeMealTracking(data) {
    try {
        fs.writeFileSync(mealTrackingDbPath, JSON.stringify(data, null, 2));
        return true;
    } catch (e) {
        console.error('Error writing meal tracking data:', e);
        return false;
    }
}

// Log a consumed meal
app.post('/api/user/:userId/meals', (req, res) => {
    const userId = parseInt(req.params.userId);
    const { foods, meal_type, dining_hall, consumed_at } = req.body;

    if (!foods || !Array.isArray(foods) || foods.length === 0) {
        return res.status(400).json({ error: 'foods array is required' });
    }

    const trackingData = readMealTracking();

    const mealEntry = {
        id: Date.now(),
        user_id: userId,
        meal_type: meal_type || 'Snack',
        dining_hall: dining_hall || 'Unknown',
        consumed_at: consumed_at || new Date().toISOString(),
        foods: foods,
        totals: {
            calories: foods.reduce((sum, f) => sum + (f.calories || 0), 0),
            protein: foods.reduce((sum, f) => sum + (f.protein || 0), 0),
            fat: foods.reduce((sum, f) => sum + (f.total_fat || 0), 0),
            carbs: foods.reduce((sum, f) => sum + (f.total_carbohydrate || 0), 0),
            fiber: foods.reduce((sum, f) => sum + (f.dietary_fiber || 0), 0),
        }
    };

    trackingData.meals.push(mealEntry);

    if (writeMealTracking(trackingData)) {
        res.status(201).json({ success: true, meal: mealEntry });
    } else {
        res.status(500).json({ error: 'Failed to save meal' });
    }
});

// Get user's meal history
app.get('/api/user/:userId/meals', (req, res) => {
    const userId = parseInt(req.params.userId);
    const { date, limit } = req.query;

    const trackingData = readMealTracking();
    let userMeals = trackingData.meals.filter(m => m.user_id === userId);

    // Filter by date if provided (YYYY-MM-DD format)
    if (date) {
        userMeals = userMeals.filter(m => m.consumed_at.startsWith(date));
    }

    // Sort by most recent first
    userMeals.sort((a, b) => new Date(b.consumed_at) - new Date(a.consumed_at));

    // Apply limit if provided
    if (limit) {
        userMeals = userMeals.slice(0, parseInt(limit));
    }

    res.json({ meals: userMeals, count: userMeals.length });
});

// Get today's nutrition totals for user
app.get('/api/user/:userId/today-totals', (req, res) => {
    const userId = parseInt(req.params.userId);
    // Use local date instead of UTC to avoid timezone issues
    const now = new Date();
    const today = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`;

    const trackingData = readMealTracking();
    const todayMeals = trackingData.meals.filter(m =>
        m.user_id === userId && m.consumed_at.startsWith(today)
    );

    const totals = {
        calories: 0,
        protein: 0,
        fat: 0,
        carbs: 0,
        fiber: 0,
        meals_count: todayMeals.length
    };

    todayMeals.forEach(meal => {
        totals.calories += meal.totals.calories || 0;
        totals.protein += meal.totals.protein || 0;
        totals.fat += meal.totals.fat || 0;
        totals.carbs += meal.totals.carbs || 0;
        totals.fiber += meal.totals.fiber || 0;
    });

    res.json({ totals, date: today, meals: todayMeals });
});

// Delete a meal entry
app.delete('/api/user/:userId/meals/:mealId', (req, res) => {
    const userId = parseInt(req.params.userId);
    const mealId = parseInt(req.params.mealId);

    const trackingData = readMealTracking();
    const mealIndex = trackingData.meals.findIndex(m =>
        m.id === mealId && m.user_id === userId
    );

    if (mealIndex === -1) {
        return res.status(404).json({ error: 'Meal not found' });
    }

    trackingData.meals.splice(mealIndex, 1);

    if (writeMealTracking(trackingData)) {
        res.json({ success: true, message: 'Meal deleted' });
    } else {
        res.status(500).json({ error: 'Failed to delete meal' });
    }
});

// Health check
app.get('/health', (req, res) => {
    res.json({ status: 'ok', timestamp: new Date().toISOString() });
});

// Start server
app.listen(PORT, () => {
    console.log(`Server running on http://localhost:${PORT}`);
    console.log(`Authentication endpoints available at:`);
    console.log(`  POST http://localhost:${PORT}/api/auth/register`);
    console.log(`  POST http://localhost:${PORT}/api/auth/login`);
    console.log(`  PUT  http://localhost:${PORT}/api/user/:userId/profile`);
    console.log(`  GET  http://localhost:${PORT}/api/user/:userId/profile`);
});
