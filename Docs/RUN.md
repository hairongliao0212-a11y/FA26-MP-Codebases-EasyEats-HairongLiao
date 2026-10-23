# Running EasyEats locally

EasyEats recommends UIUC dining-hall meals based on your nutrition goals and tracks what
you eat. It's a Flutter app backed by a small Express API, a SQLite menu database and a
Python meal planner.

## Prerequisites

- Node.js 20+
- Python **3.12** (see `.python-version`)
- Flutter **3.35+** (Dart `^3.9.2`), plus a run target: Linux/macOS/Windows desktop,
  Chrome, or an Android/iOS emulator
- No API keys or accounts needed

## 1. Backend (port 3000)

```bash
python3.12 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r Backend/scrapers/requirements.txt

cd Backend
npm ci
node server.js                     # or: npm run dev (auto-restart)
```

Keep the venv **activated** in this terminal: `server.js` spawns `python3`
(`meal-planning/meal_planner.py`) for `/api/meal-plan`, and that needs pandas/numpy.

Check it's up: `curl localhost:3000/health`. Port can be changed with `PORT=3001`.

## 2. Flutter app

```bash
cd Frontend/flutter_easyeats
flutter pub get
flutter run -d linux               # or: -d chrome, -d macos, -d windows, or an emulator
```

The API base URL is hard-coded to `http://localhost:3000` in
`lib/services/auth_service.dart`, `lib/services/nutrition_service.dart`,
`lib/pages/change_password_page.dart` and `lib/pages/dining1_ike.dart`.
On an **Android emulator** change it to `http://10.0.2.2:3000`; on a physical phone use
your computer's LAN IP.

## Data

| File | Contents |
|---|---|
| `Backend/data/nutrition_data.db` | SQLite menu + nutrition data (table `nutrition_data`) |
| `Backend/data/users.json` | User accounts (PBKDF2-hashed passwords) and profiles |
| `Backend/data/meal_tracking.json` | Logged meals |

The menu DB was loaded from an October 2026 scrape with allergen/diet traits: Ikenberry for
Oct 22–23, the other locations for Oct 23–24, and Kosher Kitchen for Oct 25–26 (it has no
menus Friday–Saturday). It covers 11 locations and every meal period of each day.
Menus don't repeat weekly (ISR Fusion 48 runs a 14-day cycle), so re-scrape regularly.

To refresh menus:

```bash
cd Backend/scrapers
python nutrition_scraper.py        # Selenium; needs Google Chrome installed. Needs a steady
                                   # connection: locations it can't reach are skipped, not retried
python load_to_db.py <output>.xlsx # replaces the contents of ../data/nutrition_data.db
```

### Dietary restrictions

The scraper saves the allergen and diet icons eatsmart shows beside each dish (Milk, Wheat,
Vegan, Halal, ...) in the `traits` column. [`Backend/dietary_rules.json`](../Backend/dietary_rules.json)
maps each restriction a user can pick to those traits; both `server.js` (via `dietary.js`) and
`meal_planner.py` read it.

- `/api/recommendations/:userId` and `/api/meal-plan?user_id=` only return dishes that fit
  every one of the user's restrictions.
- `/api/dining-halls/:hall/foods?user_id=` returns every dish, each with a `conflicts` list.
- A dish with `traits` NULL (data scraped before traits existed) can't be verified, so it is
  excluded whenever the user has a restriction.
- Low Sodium, Low Sugar, Keto and Paleo have no eatsmart labels, so they are listed under
  `_not_checked` and ignored.

## Tests

```bash
# From the repository root, with the venv active
python -m unittest discover -s Backend/tests -v   # scraper parsing, loader, meal planner
cd Backend && npm test                            # API (starts its own server on port 3999)
cd Frontend/flutter_easyeats && flutter test test/food_item_test.dart
```

## Code map

```
Backend/
  server.js               Express API (routes listed in Docs/API_HANDBOOK.md)
  auth.js                 file-based user store + password hashing
  dietary.js              dietary restriction checks (rules in dietary_rules.json)
  tests/                  Python + Node tests
  meal-planning/          Python meal planner called by /api/meal-plan
  scrapers/               dining-site scraper + Excel -> SQLite loader
Frontend/flutter_easyeats/lib/
  pages/  services/  models/
WebScraping/, Research/   earlier experiments
*.xlsx, *.csv (root)      raw scrape exports
```

API reference: [`API_HANDBOOK.md`](API_HANDBOOK.md).
