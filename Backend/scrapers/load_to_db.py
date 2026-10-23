"""
Load scraped nutrition data from Excel into SQLite database
"""
import sqlite3
import pandas as pd
import os
from datetime import datetime


def create_nutrition_table(conn):
    """Create the nutrition table if it doesn't exist"""
    cursor = conn.cursor()

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS nutrition_data (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            dining_hall TEXT NOT NULL,
            service TEXT NOT NULL,
            date TEXT NOT NULL,
            meal_type TEXT NOT NULL,
            category TEXT,
            name TEXT NOT NULL,
            traits TEXT,
            serving_size TEXT,
            calories REAL,
            total_fat REAL,
            saturated_fat REAL,
            trans_fat REAL,
            cholesterol REAL,
            sodium REAL,
            potassium REAL,
            total_carbohydrate REAL,
            dietary_fiber REAL,
            sugars REAL,
            protein REAL,
            scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Databases created before traits were scraped need the column added
    cursor.execute("PRAGMA table_info(nutrition_data)")
    columns = [row[1] for row in cursor.fetchall()]
    if 'traits' not in columns:
        cursor.execute("ALTER TABLE nutrition_data ADD COLUMN traits TEXT")
        print("✓ Added 'traits' column")

    # Create indexes for faster queries
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_dining_hall
        ON nutrition_data(dining_hall)
    ''')

    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_date_meal
        ON nutrition_data(date, meal_type)
    ''')

    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_name
        ON nutrition_data(name)
    ''')

    conn.commit()
    print("✓ Table 'nutrition_data' created/verified")


def load_excel_to_database(excel_file, db_file='../data/nutrition_data.db'):
    """
    Load nutrition data from Excel file into SQLite database

    Args:
        excel_file: Path to the Excel file with nutrition data
        db_file: Path to SQLite database file (will be created if doesn't exist)
    """

    # Check if Excel file exists
    if not os.path.exists(excel_file):
        print(f"Error: Excel file not found: {excel_file}")
        return False

    print(f"\nLoading data from: {excel_file}")
    print(f"Database: {db_file}\n")

    # Read Excel file
    try:
        df = pd.read_excel(excel_file)
        print(f"✓ Read {len(df)} rows from Excel")
    except Exception as e:
        print(f"Error reading Excel file: {e}")
        return False

    # Connect to database
    conn = sqlite3.connect(db_file)

    # Create table
    create_nutrition_table(conn)

    # Prepare data for insertion
    cursor = conn.cursor()

    # Clear existing data (optional - comment out if you want to append)
    cursor.execute("DELETE FROM nutrition_data")
    print("✓ Cleared existing data")

    # Excel files from before traits were scraped have no traits column.
    # Their traits are unknown (NULL), which is different from a dish with no trait icons ('').
    has_traits = 'traits' in df.columns
    if not has_traits:
        print("! No 'traits' column in Excel file - dietary restrictions can't be checked for this data")

    # Insert data
    inserted = 0
    failed = 0

    for idx, row in df.iterrows():
        if has_traits:
            traits = row['traits'] if pd.notna(row['traits']) else ''
        else:
            traits = None

        try:
            cursor.execute('''
                INSERT INTO nutrition_data (
                    dining_hall, service, date, meal_type, category, name, traits,
                    serving_size, calories, total_fat, saturated_fat, trans_fat,
                    cholesterol, sodium, potassium, total_carbohydrate,
                    dietary_fiber, sugars, protein
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                row.get('dining_hall', ''),
                row.get('service', ''),
                row.get('date', ''),
                row.get('meal_type', ''),
                row.get('category', ''),
                row.get('name', ''),
                traits,
                row.get('serving_size', ''),
                float(row.get('calories', 0)) if pd.notna(row.get('calories')) else 0.0,
                float(row.get('total_fat', 0)) if pd.notna(row.get('total_fat')) else 0.0,
                float(row.get('saturated_fat', 0)) if pd.notna(row.get('saturated_fat')) else 0.0,
                float(row.get('trans_fat', 0)) if pd.notna(row.get('trans_fat')) else 0.0,
                float(row.get('cholesterol', 0)) if pd.notna(row.get('cholesterol')) else 0.0,
                float(row.get('sodium', 0)) if pd.notna(row.get('sodium')) else 0.0,
                float(row.get('potassium', 0)) if pd.notna(row.get('potassium')) else 0.0,
                float(row.get('total_carbohydrate', 0)) if pd.notna(row.get('total_carbohydrate')) else 0.0,
                float(row.get('dietary_fiber', 0)) if pd.notna(row.get('dietary_fiber')) else 0.0,
                float(row.get('sugars', 0)) if pd.notna(row.get('sugars')) else 0.0,
                float(row.get('protein', 0)) if pd.notna(row.get('protein')) else 0.0
            ))
            inserted += 1
        except Exception as e:
            print(f"Error inserting row {idx}: {e}")
            failed += 1

    conn.commit()

    print(f"\n✓ Inserted {inserted} rows")
    if failed > 0:
        print(f"✗ Failed to insert {failed} rows")

    # Display summary statistics
    print("\n" + "="*60)
    print("DATABASE SUMMARY")
    print("="*60)

    cursor.execute("SELECT COUNT(*) FROM nutrition_data")
    total = cursor.fetchone()[0]
    print(f"Total items: {total}")

    cursor.execute("SELECT COUNT(DISTINCT dining_hall) FROM nutrition_data")
    halls = cursor.fetchone()[0]
    print(f"Dining halls: {halls}")

    cursor.execute("SELECT COUNT(DISTINCT date) FROM nutrition_data")
    dates = cursor.fetchone()[0]
    print(f"Unique dates: {dates}")

    cursor.execute("SELECT COUNT(DISTINCT meal_type) FROM nutrition_data")
    meals = cursor.fetchone()[0]
    print(f"Meal types: {meals}")

    cursor.execute("SELECT COUNT(*) FROM nutrition_data WHERE traits IS NOT NULL AND traits != ''")
    with_traits = cursor.fetchone()[0]
    print(f"Items with allergen/diet traits: {with_traits}")

    # Show sample data
    print("\n" + "="*60)
    print("SAMPLE DATA (First 5 items)")
    print("="*60)

    cursor.execute("""
        SELECT dining_hall, date, meal_type, name, calories
        FROM nutrition_data
        LIMIT 5
    """)

    for row in cursor.fetchall():
        print(f"{row[0]} | {row[1]} | {row[2]} | {row[3]} | {row[4]} cal")

    conn.close()
    print(f"\n✓ Database saved to: {db_file}")

    return True


def query_database(db_file='../data/nutrition_data.db'):
    """Example queries to demonstrate database usage"""

    if not os.path.exists(db_file):
        print(f"Database not found: {db_file}")
        return

    conn = sqlite3.connect(db_file)
    cursor = conn.cursor()

    print("\n" + "="*60)
    print("EXAMPLE QUERIES")
    print("="*60)

    # Query 1: Items by dining hall
    print("\n1. Items by dining hall:")
    cursor.execute("""
        SELECT dining_hall, COUNT(*) as item_count
        FROM nutrition_data
        GROUP BY dining_hall
        ORDER BY item_count DESC
    """)
    for row in cursor.fetchall():
        print(f"   {row[0]}: {row[1]} items")

    # Query 2: High protein items
    print("\n2. High protein items (>20g):")
    cursor.execute("""
        SELECT name, protein, dining_hall, meal_type
        FROM nutrition_data
        WHERE protein > 20
        ORDER BY protein DESC
        LIMIT 5
    """)
    for row in cursor.fetchall():
        print(f"   {row[0]} - {row[1]}g protein ({row[2]}, {row[3]})")

    # Query 3: Average calories by meal type
    print("\n3. Average calories by meal type:")
    cursor.execute("""
        SELECT meal_type, ROUND(AVG(calories), 1) as avg_calories
        FROM nutrition_data
        GROUP BY meal_type
        ORDER BY avg_calories DESC
    """)
    for row in cursor.fetchall():
        print(f"   {row[0]}: {row[1]} calories")

    conn.close()


if __name__ == "__main__":
    import sys

    # Check for command line argument
    if len(sys.argv) > 1:
        excel_file = sys.argv[1]
    else:
        # Default: look for the most recent Excel file in current directory
        excel_files = [f for f in os.listdir('.') if f.endswith('.xlsx') and not f.startswith('~')]

        if not excel_files:
            print("No Excel files found in current directory")
            print("\nUsage: python load_to_database.py [excel_file.xlsx]")
            sys.exit(1)

        # Use most recently modified Excel file
        excel_files.sort(key=lambda x: os.path.getmtime(x), reverse=True)
        excel_file = excel_files[0]
        print(f"Using most recent Excel file: {excel_file}")

    # Load data
    success = load_excel_to_database(excel_file)

    if success:
        # Show example queries
        query_database()

        print("\n" + "="*60)
        print("Next steps:")
        print("  - Query database using SQLite tools or Python")
        print("  - Use for meal planning, nutrition tracking, etc.")
        print("  - Integrate with your app/website")
        print("="*60)
