from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
import time
from bs4 import BeautifulSoup
import pandas as pd
from datetime import datetime, timedelta
import json
import re


def extract_traits_from_html(item_html):
    """Return the trait icon titles (allergens and diets, e.g. 'Milk', 'Vegan') in a menu item's HTML.

    On eatsmart each trait is an <img title="..."> next to the food name.
    """
    soup = BeautifulSoup(item_html or '', 'html.parser')
    traits = []
    for img in soup.find_all('img'):
        title = (img.get('title') or '').strip()
        if title and title not in traits:
            traits.append(title)
    return traits


class NutritionScraperComplete:
    def __init__(self, testing_mode=False):
        """Initialize the scraper with Chrome options
        
        Args:
            testing_mode (bool): If True, limits scraping for faster testing
        """
        options = webdriver.ChromeOptions()
        options.add_argument('--headless')
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument('--disable-blink-features=AutomationControlled')
        options.add_argument('user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36')
        # Force English so menu dates are stored as e.g. "Thursday, October 22, 2026"
        # rather than in the computer's language
        options.add_argument('--lang=en-US')
        options.add_experimental_option('prefs', {'intl.accept_languages': 'en-US,en'})

        self.options = options
        self.start_browser()
        self.base_url = "https://eatsmart.housing.illinois.edu"
        self.testing_mode = testing_mode
        self.max_items_per_meal = 5 if testing_mode else None

    def start_browser(self):
        """Start (or restart) headless Chrome"""
        self.driver = webdriver.Chrome(options=self.options)
        self.wait = WebDriverWait(self.driver, 15)

    def browser_alive(self):
        """Check whether the browser session still responds"""
        try:
            self.driver.current_url
            return True
        except Exception:
            return False

    def restart_browser(self):
        """Replace a crashed browser so scraping can continue with the next service"""
        print("Browser session lost - restarting Chrome...")
        try:
            self.driver.quit()
        except Exception:
            pass
        self.start_browser()

    def scrape_dining_structure(self):
        """Scrape all dining halls and their services from the dropdown menu"""
        try:
            print("Loading main page to extract dining hall structure...")
            self.driver.get(self.base_url + "/NetNutrition/1")
            time.sleep(4)
            
            print("Extracting dining halls and services from navigation dropdown...")
            
            dropdown = self.driver.find_element(By.ID, "nav-unit-selector")
            dropdown_items = dropdown.find_elements(By.CSS_SELECTOR, ".dropdown-item")
            
            dining_halls = []
            current_hall = None

            def add_hall(hall):
                # Stand-alone locations (e.g. Kosher Kitchen) have no services under them;
                # their menus are on the location itself, so scrape it as its own service
                if not hall['dining_services']:
                    hall['dining_services'].append({
                        'service_name': hall['dining_hall'],
                        'service_id': hall['unit_id']
                    })
                dining_halls.append(hall)

            for item in dropdown_items:
                try:
                    link = item.find_element(By.TAG_NAME, "a")
                    name = link.get_attribute('title') or link.text.strip()
                    unit_id = link.get_attribute('data-unitoid')
                    
                    if not name or not unit_id or unit_id == '-1':
                        continue
                    
                    is_primary = 'text-primary' in link.get_attribute('class')
                    
                    if is_primary:
                        if current_hall:
                            add_hall(current_hall)
                        
                        current_hall = {
                            'dining_hall': name,
                            'unit_id': unit_id,
                            'dining_services': []
                        }
                    else:
                        if current_hall:
                            service = {
                                'service_name': name,
                                'service_id': unit_id
                            }
                            current_hall['dining_services'].append(service)
                
                except Exception as e:
                    continue
            
            if current_hall:
                add_hall(current_hall)

            return dining_halls
            
        except Exception as e:
            print(f"Error scraping dining structure: {str(e)}")
            return []
    
    def navigate_to_service(self, unit_id, service_name, retry=True):
        """Navigate to a specific dining service"""
        try:
            print(f"\nNavigating to {service_name} (ID: {unit_id})...")
            
            self.driver.get(f"{self.base_url}/NetNutrition/1")
            time.sleep(4)
            
            dropdown = self.driver.find_element(By.ID, "nav-unit-selector")
            service_link = dropdown.find_element(By.CSS_SELECTOR, f"a[data-unitoid='{unit_id}']")
            
            self.driver.execute_script("arguments[0].click();", service_link)
            
            # Wait for date selector to appear instead of fixed sleep
            self.wait.until(EC.presence_of_element_located((By.ID, "nav-date-selector")))
            time.sleep(1) # Small buffer
            
            print("Service loaded")
            return True

        except Exception as e:
            print(f"Error: {str(e)}")
            # Headless Chrome occasionally crashes on long runs; start a new one and try once more
            if retry and not self.browser_alive():
                self.restart_browser()
                return self.navigate_to_service(unit_id, service_name, retry=False)
            return False

    def get_available_dates_for_next_n_days(self, n_days=7):
        """Get available dates from the date selector dropdown for the next n days (including today)"""
        try:
            print(f"\nGetting available dates for next {n_days} days...")

            # Find the date selector dropdown
            date_selector = self.driver.find_element(By.ID, "nav-date-selector")
            date_items = date_selector.find_elements(By.CSS_SELECTOR, "a.dropdown-item")

            # Get today's date
            today = datetime.now().date()

            # Target dates (today + next n-1 days)
            target_dates = [today + timedelta(days=i) for i in range(n_days)]

            available_dates = []

            for item in date_items:
                try:
                    data_date = item.get_attribute('data-date')
                    title = item.get_attribute('title')

                    if data_date == "Today":
                        # Today's date
                        available_dates.append({
                            'element': item,
                            'data_date': data_date,
                            'date': today,
                            'date_str': today.strftime('%A, %B %d, %Y'),
                            'title': title
                        })
                        print(f"  ✓ Found: Today ({today.strftime('%m/%d/%Y')})")

                    elif data_date and data_date not in ["Show All Dates"]:
                        # Parse date from data-date attribute (format: "11/14/2025")
                        try:
                            date_obj = datetime.strptime(data_date, '%m/%d/%Y').date()

                            # Check if this date is in our target range
                            if date_obj in target_dates:
                                available_dates.append({
                                    'element': item,
                                    'data_date': data_date,
                                    'date': date_obj,
                                    'date_str': title,
                                    'title': title
                                })
                                print(f"  ✓ Found: {title}")
                        except ValueError:
                            # Invalid date format, skip
                            pass

                except Exception as e:
                    continue

            # Sort by date
            available_dates.sort(key=lambda x: x['date'])

            print(f"\nFound {len(available_dates)} dates out of {n_days} requested days")
            return available_dates

        except Exception as e:
            print(f"Error getting available dates: {str(e)}")
            import traceback
            traceback.print_exc()
            return []

    def select_date(self, date_element):
        """Select a specific date from the dropdown"""
        try:
            # Click on the date element using JavaScript (more reliable)
            # Click on the date element using JavaScript (more reliable)
            self.driver.execute_script("arguments[0].click();", date_element)
            
            # Wait for results panel to update
            self.wait.until(EC.presence_of_element_located((By.ID, "navBarResults")))
            time.sleep(1)
            return True
        except Exception as e:
            print(f"Error selecting date: {str(e)}")
            return False

    def get_all_meals_structured(self):
        """Get all available meals organized by date and meal period"""
        try:
            print("Extracting meal structure...")
            time.sleep(3)

            results_panel = self.driver.find_element(By.ID, "navBarResults")

            # Get all menu items (the clickable li elements with date/meal info)
            menu_items = results_panel.find_elements(By.CSS_SELECTOR, "li.list-group-item")
            print(f"Found {len(menu_items)} menu items")

            structured_meals = []

            # Extract date and meal from each menu item directly
            for menu_item in menu_items:
                try:
                    # Use textContent to get the text (works better in headless mode than .text)
                    date_meal_text = menu_item.get_attribute('textContent')

                    if not date_meal_text or not date_meal_text.strip():
                        # Fallback: try innerText
                        date_meal_text = menu_item.get_attribute('innerText')

                    if not date_meal_text or not date_meal_text.strip():
                        print(f"  Warning: Could not extract text from menu item")
                        continue

                    date_meal_text = date_meal_text.strip()

                    # Parse the format "Date-MealType" (e.g., "Thursday, November 13, 2025-Breakfast")
                    if '-' in date_meal_text:
                        parts = date_meal_text.rsplit('-', 1)
                        if len(parts) == 2:
                            date_part = parts[0].strip()
                            meal_part = parts[1].strip()

                            # Extract meal type
                            meal_types = ['Breakfast', 'Lunch', 'Dinner', 'Brunch', 'Late Night']
                            meal_type = None
                            for meal in meal_types:
                                if meal.lower() in meal_part.lower():
                                    meal_type = meal
                                    break

                            if not meal_type:
                                meal_type = meal_part  # Use as-is if not in standard list

                            meal_info = {
                                'element': menu_item,
                                'date': date_part,
                                'meal_type': meal_type,
                                'onclick': menu_item.get_attribute('onclick')
                            }
                            structured_meals.append(meal_info)
                            print(f"  Parsed: {date_part} - {meal_type}")
                    else:
                        print(f"  Warning: Could not parse date/meal from: {date_meal_text}")

                except Exception as e:
                    print(f"  Error processing menu item: {str(e)}")
                    continue

            print(f"\nStructured {len(structured_meals)} meal periods")

            return structured_meals

        except Exception as e:
            print(f"Error getting meal structure: {str(e)}")
            import traceback
            traceback.print_exc()
            return []
    
    def click_meal(self, meal_element):
        """Click on a specific meal to load its items"""
        try:
            print("Clicking meal...")
            
            # Try to get the onclick attribute and execute it directly
            onclick = meal_element.get_attribute('onclick')
            if onclick:
                print(f"  Using onclick: {onclick}")
                self.driver.execute_script(onclick)
            else:
                # Fallback to clicking the element
                self.driver.execute_script("arguments[0].click();", meal_element)
            
            # Wait for items to load instead of fixed sleep
            # Look for either items or the "no items" message
            try:
                self.wait.until(lambda d: 
                    len(d.find_elements(By.CSS_SELECTOR, "a.cbo_nn_itemHover")) > 0 or 
                    len(d.find_elements(By.CSS_SELECTOR, "tr.cbo_nn_itemGroupRow")) > 0
                )
            except:
                time.sleep(2) # Fallback if wait times out
                
            print("Meal loaded")
            return True
        except Exception as e:
            print(f"Error clicking meal: {str(e)}")
            return False
    
    def extract_category_map(self):
        """Extract the mapping of category IDs to category names"""
        try:
            category_map = {}
            # Find category header rows
            category_rows = self.driver.find_elements(By.CSS_SELECTOR, "tr.cbo_nn_itemGroupRow")

            for row in category_rows:
                try:
                    # Try to find the div with role="button" that contains the category name
                    category_name = ""
                    try:
                        category_div = row.find_element(By.CSS_SELECTOR, "div[role='button']")
                        # Get the innerHTML and parse it to extract just the text
                        innerHTML = category_div.get_attribute('innerHTML')
                        if innerHTML:
                            # Parse HTML to get text before the <i> tag
                            from bs4 import BeautifulSoup
                            soup = BeautifulSoup(innerHTML, 'html.parser')
                            # Get text, which will include the category name
                            category_name = soup.get_text().strip()
                            # Remove any trailing whitespace or icon text
                            category_name = category_name.split('\n')[0].strip()
                    except:
                        # Fallback: try to get text directly
                        category_name = row.text.strip()

                    # Find the category ID by looking at the next sibling row with data-categoryid
                    # Use JavaScript to get the next element sibling
                    next_row = self.driver.execute_script(
                        "return arguments[0].nextElementSibling;", row
                    )

                    if next_row:
                        cat_id = next_row.get_attribute('data-categoryid')
                        if cat_id and category_name:
                            category_map[cat_id] = category_name
                            print(f"     Found category: ID {cat_id} = '{category_name}'")

                except Exception as e:
                    continue

            return category_map

        except Exception as e:
            print(f"     Error extracting categories: {str(e)}")
            return {}

    def extract_nutrition_info(self, max_items=None):
        """Extract nutrition information for each menu item by clicking on them"""
        try:
            print("Extracting nutrition information...")

            # First, extract the category map
            print("  Extracting categories...")
            category_map = self.extract_category_map()

            items_data = []
            items = self.driver.find_elements(By.CSS_SELECTOR, "a.cbo_nn_itemHover")
            print(f"Found {len(items)} clickable items")

            if len(items) == 0:
                print("No clickable items found!")
                return items_data

            # Limit items for testing if max_items is specified
            if max_items:
                items_to_process = items[:max_items]
                print(f"Processing first {len(items_to_process)} items (testing mode)\n")
            else:
                items_to_process = items
                print(f"Processing all {len(items_to_process)} items\n")

            for i, item in enumerate(items_to_process, 1):
                try:
                    # Extract food name
                    food_name = ""
                    try:
                        food_name = item.text.strip()
                    except:
                        pass

                    if not food_name:
                        try:
                            inner_html = item.get_attribute('innerHTML')
                            soup = BeautifulSoup(inner_html, 'html.parser')
                            food_name = soup.get_text().strip()
                        except:
                            pass

                    # Extract category by finding the parent tr and its data-categoryid
                    category = "Unknown"
                    try:
                        tr_element = self.driver.execute_script("return arguments[0].closest('tr');", item)
                        cat_id = tr_element.get_attribute('data-categoryid')
                        if cat_id and cat_id in category_map:
                            category = category_map[cat_id]
                    except:
                        pass

                    # Extract allergen and diet traits from the icons beside the name
                    traits = []
                    try:
                        traits = extract_traits_from_html(item.get_attribute('innerHTML'))
                    except:
                        pass

                    print(f"  {i}. {food_name} [{category}] {traits}")

                    if not food_name:
                        continue

                    # Click to open nutrition modal
                    print(f"     → Clicking...")
                    try:
                        self.driver.execute_script("arguments[0].scrollIntoView(true);", item)
                        # time.sleep(0.5) # Removed small sleep
                        self.driver.execute_script("arguments[0].click();", item)
                    except:
                        item.click()

                    # Wait for modal to appear
                    try:
                        self.wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "div[class*='modal'][class*='show'], div[role='dialog']")))
                        time.sleep(0.5) # Buffer to ensure text renders
                    except:
                        time.sleep(1) # Fallback

                    # Extract nutrition info
                    nutrition_info = self.extract_nutrition_from_modal(food_name)
                    nutrition_info['category'] = category  # Add category to the nutrition info
                    nutrition_info['traits'] = traits
                    items_data.append(nutrition_info)

                    if nutrition_info.get('nutrition'):
                        print(f"     ✓ Extracted {len(nutrition_info['nutrition'])} nutrition fields")
                    else:
                        print(f"     ✗ No nutrition data found")

                    # Close modal
                    self.close_modal()
                    # No sleep needed after close, we just move to next item

                except Exception as e:
                    print(f"    ERROR: {str(e)}")
                    continue

            print(f"\n✓ Extracted nutrition info for {len(items_data)} items")
            return items_data

        except Exception as e:
            print(f"Error: {str(e)}")
            return []
    
    def close_modal(self):
        """Close any open modal"""
        try:
            # Try various methods to close modal
            close_selectors = [
                "button[class*='close']",
                "button[aria-label*='close']",
                ".modal button.close",
                "button[data-dismiss='modal']"
            ]
            
            for selector in close_selectors:
                try:
                    close_button = self.driver.find_element(By.CSS_SELECTOR, selector)
                    self.driver.execute_script("arguments[0].click();", close_button)
                    return
                except:
                    pass
            
            # Try Escape key
            try:
                self.driver.execute_script("document.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape'}))")
            except:
                pass
                
        except Exception as e:
            print(f"     Error closing modal: {str(e)}")
    
    def extract_nutrition_from_modal(self, food_name):
        """Extract nutrition information from the modal"""
        nutrition_info = {
            'name': food_name,
            'serving_size': None,
            'nutrition': {}
        }
        
        try:
            # Find modal
            modal_body = None
            modal_selectors = [
                "div[class*='modal'][class*='show']",
                "div[role='dialog']",
                "div[class*='popup']"
            ]
            
            for selector in modal_selectors:
                try:
                    modal_body = self.driver.find_element(By.CSS_SELECTOR, selector)
                    break
                except:
                    pass
            
            if not modal_body:
                modal_body = self.driver.find_element(By.TAG_NAME, "body")
            
            modal_text = modal_body.text
            
            if not modal_text or len(modal_text) < 20:
                return nutrition_info
            
            lines = modal_text.split('\n')
            
            # Nutrition fields to extract
            nutrition_keywords = {
                'calories': ['calories'],
                'total_fat': ['total fat'],
                'saturated_fat': ['saturated fat'],
                'trans_fat': ['trans fat'],
                'cholesterol': ['cholesterol'],
                'sodium': ['sodium'],
                'potassium': ['potassium'],
                'total_carbohydrate': ['total carbohydrate', 'carbohydrate'],
                'dietary_fiber': ['dietary fiber'],
                'sugars': ['sugars'],
                'protein': ['protein']
            }
            
            for line in lines:
                line_lower = line.lower().strip()
                
                # Parse serving size
                if 'serving size' in line_lower:
                    nutrition_info['serving_size'] = line.split(':', 1)[-1].strip() if ':' in line else line
                
                # Parse nutrition values
                for key, keywords in nutrition_keywords.items():
                    for keyword in keywords:
                        if keyword in line_lower and key not in nutrition_info['nutrition']:
                            value = self.extract_nutrition_value(line, keyword)
                            if value:
                                nutrition_info['nutrition'][key] = value
                            break
            
        except Exception as e:
            print(f"       ERROR extracting nutrition: {str(e)}")
        
        return nutrition_info
    
    def parse_nutrition_value(self, value_str):
        """Parse nutrition value and convert to grams (standardized format)

        Handles:
        - mg to g conversion (1000mg = 1g)
        - Removes units (g, mg)
        - Converts N/A, empty, or 0 to "0"
        - Returns numeric value as string without units

        Examples:
        - "500mg" -> "0.5"
        - "2.5g" -> "2.5"
        - "N/A" -> "0"
        - "0g" -> "0"
        """
        if not value_str or value_str.strip() == "":
            return "0"

        value_str = str(value_str).strip().upper()

        # Handle N/A cases
        if value_str in ["N/A", "NA", "NONE", "-", ""]:
            return "0"

        try:
            # Extract numeric value and unit
            # Match patterns like "500mg", "2.5g", "500 mg", "2.5 g", "500"
            match = re.match(r'^\s*([0-9.]+)\s*(MG|G|GRAMS?|MILLIGRAMS?)?\s*$', value_str, re.IGNORECASE)

            if match:
                numeric_value = float(match.group(1))
                unit = match.group(2)

                # Convert to grams if needed
                if unit and unit.upper() in ['MG', 'MILLIGRAM', 'MILLIGRAMS']:
                    # Convert mg to g
                    numeric_value = numeric_value / 1000.0

                # Return 0 if the value is 0
                if numeric_value == 0:
                    return "0"

                # Format the number - remove trailing zeros
                if numeric_value == int(numeric_value):
                    return str(int(numeric_value))
                else:
                    # Keep up to 3 decimal places, remove trailing zeros
                    return f"{numeric_value:.3f}".rstrip('0').rstrip('.')
            else:
                # If no match, try to extract just numbers
                numbers = re.findall(r'[0-9.]+', value_str)
                if numbers:
                    numeric_value = float(numbers[0])
                    if numeric_value == 0:
                        return "0"
                    if numeric_value == int(numeric_value):
                        return str(int(numeric_value))
                    else:
                        return f"{numeric_value:.3f}".rstrip('0').rstrip('.')
                return "0"
        except Exception:
            # If parsing fails, return "0"
            return "0"

    def extract_nutrition_value(self, line, keyword):
        """Extract nutrition value from a line and parse it to standardized format"""
        try:
            keyword_pos = line.lower().find(keyword)
            if keyword_pos == -1:
                return "0"

            after_keyword = line[keyword_pos + len(keyword):].strip()

            value = ""
            for char in after_keyword:
                if char.isspace() and value:
                    break
                if char == '%':
                    break
                value += char

            value = value.strip()

            # Parse and standardize the value
            return self.parse_nutrition_value(value) if value else "0"

        except:
            return "0"
    
    def scrape_all_with_complete_data(self, days_to_scrape=7):
        """Scrape all dining halls with nutrition info for the next n days (including today)

        Args:
            days_to_scrape: Number of days to scrape (default: 7, including today)
        """
        all_results = []

        print("="*80)
        print(f"Illinois Dining Complete Scraper - {days_to_scrape} Days")
        print("="*80)

        dining_halls = self.scrape_dining_structure()

        if not dining_halls:
            print("Failed to get dining structure")
            return all_results

        # Testing mode limitations
        if self.testing_mode:
            print("\n[TESTING MODE] Limiting to first dining hall, first service, and first 2 days")
            dining_halls = dining_halls[:1]  # Only first dining hall
            if dining_halls and dining_halls[0]['dining_services']:
                dining_halls[0]['dining_services'] = dining_halls[0]['dining_services'][:1]  # Only first service
            days_to_scrape = min(days_to_scrape, 2)  # Limit to 2 days in testing mode

        for hall in dining_halls:
            hall_name = hall['dining_hall']

            print(f"\n{'='*80}")
            print(f"Processing: {hall_name}")
            print(f"{'='*80}")

            if not hall['dining_services']:
                continue

            for service in hall['dining_services']:
                service_name = service['service_name']
                service_id = service['service_id']

                if not self.navigate_to_service(service_id, service_name):
                    continue

                # Get available dates for the next n days
                available_dates = self.get_available_dates_for_next_n_days(days_to_scrape)

                if not available_dates:
                    print(f"No dates available for scraping")
                    continue

                # Store date strings (not elements, which become stale)
                target_dates = [(d['data_date'], d['date_str']) for d in available_dates]

                print(f"\n{'='*80}")
                print(f"Scraping {len(target_dates)} days for {service_name}")
                print(f"{'='*80}")

                # Scrape each date
                for date_idx, (data_date, date_str) in enumerate(target_dates, 1):
                    print(f"\n{'='*60}")
                    print(f"Date {date_idx}/{len(target_dates)}: {date_str}")
                    print(f"{'='*60}")

                    # Find and select this date (refresh the element each time to avoid stale elements)
                    try:
                        date_selector = self.driver.find_element(By.ID, "nav-date-selector")
                        date_items = date_selector.find_elements(By.CSS_SELECTOR, "a.dropdown-item")

                        # Find the matching date element
                        date_element = None
                        for item in date_items:
                            if item.get_attribute('data-date') == data_date:
                                date_element = item
                                break

                        if not date_element:
                            print(f"Could not find date element for: {date_str}")
                            continue

                        # Select this date
                        if not self.select_date(date_element):
                            print(f"Failed to select date: {date_str}")
                            continue

                    except Exception as e:
                        print(f"Error finding/selecting date: {str(e)}")
                        continue

                    # Get all meals for this date
                    structured_meals = self.get_all_meals_structured()

                    if not structured_meals:
                        print(f"No meals found for {date_str}")
                        continue

                    # Testing mode: limit number of meals per day
                    if self.testing_mode:
                        print(f"[TESTING MODE] Limiting to first meal period only")
                        structured_meals = structured_meals[:1]  # Only process first meal

                    for meal_idx, meal_info in enumerate(structured_meals):
                        if not meal_info['element']:
                            continue

                        print(f"\n[Meal {meal_idx + 1}/{len(structured_meals)}]")
                        print(f"Date: {meal_info['date']}, Meal: {meal_info['meal_type']}")

                        # After the first meal the page was reloaded, so the saved element is stale;
                        # look the meal up again on the fresh page
                        meal_element = meal_info['element']
                        if meal_idx > 0:
                            fresh_meals = self.get_all_meals_structured()
                            meal_element = next(
                                (m['element'] for m in fresh_meals
                                 if m['date'] == meal_info['date'] and m['meal_type'] == meal_info['meal_type']),
                                None
                            )
                            if not meal_element:
                                print(f"Could not find {meal_info['meal_type']} after reloading")
                                continue

                        if not self.click_meal(meal_element):
                            continue

                        # Extract nutrition info
                        nutrition_items = self.extract_nutrition_info(max_items=self.max_items_per_meal)

                        # Store results with meal info
                        for item_data in nutrition_items:
                            # Get category
                            category = item_data.get('category', 'Unknown')

                            result = {
                                'dining_hall': hall_name,
                                'service': service_name,
                                'date': meal_info['date'],
                                'meal_type': meal_info['meal_type'],
                                'category': category,  # Category column shows what type of food
                                'name': item_data['name'],
                                'traits': ', '.join(item_data.get('traits', [])),  # e.g. "Eggs, Milk, Vegetarian"
                                'serving_size': item_data.get('serving_size'),
                                'calories': self.parse_nutrition_value(item_data.get('nutrition', {}).get('calories', '0')),
                                'total_fat': self.parse_nutrition_value(item_data.get('nutrition', {}).get('total_fat', '0')),
                                'saturated_fat': self.parse_nutrition_value(item_data.get('nutrition', {}).get('saturated_fat', '0')),
                                'trans_fat': self.parse_nutrition_value(item_data.get('nutrition', {}).get('trans_fat', '0')),
                                'cholesterol': self.parse_nutrition_value(item_data.get('nutrition', {}).get('cholesterol', '0')),
                                'sodium': self.parse_nutrition_value(item_data.get('nutrition', {}).get('sodium', '0')),
                                'potassium': self.parse_nutrition_value(item_data.get('nutrition', {}).get('potassium', '0')),
                                'total_carbohydrate': self.parse_nutrition_value(item_data.get('nutrition', {}).get('total_carbohydrate', '0')),
                                'dietary_fiber': self.parse_nutrition_value(item_data.get('nutrition', {}).get('dietary_fiber', '0')),
                                'sugars': self.parse_nutrition_value(item_data.get('nutrition', {}).get('sugars', '0')),
                                'protein': self.parse_nutrition_value(item_data.get('nutrition', {}).get('protein', '0'))
                            }
                            all_results.append(result)

                        print(f"Stored nutrition for {len(nutrition_items)} items")

                        # Navigate back for next meal within the same date
                        if meal_idx < len(structured_meals) - 1:
                            print("Navigating back to service for next meal...")
                            if not self.navigate_to_service(service_id, service_name):
                                break

                            # Re-find and reselect the same date
                            try:
                                date_selector = self.driver.find_element(By.ID, "nav-date-selector")
                                date_items = date_selector.find_elements(By.CSS_SELECTOR, "a.dropdown-item")

                                date_element = None
                                for item in date_items:
                                    if item.get_attribute('data-date') == data_date:
                                        date_element = item
                                        break

                                if date_element and not self.select_date(date_element):
                                    break
                            except Exception as e:
                                print(f"Error reselecting date: {str(e)}")
                                break

                    # After finishing all meals for this date, navigate back for next date
                    if date_idx < len(target_dates):
                        print(f"\nFinished {date_str}, preparing for next date...")
                        if not self.navigate_to_service(service_id, service_name):
                            break
        
        print(f"\n{'='*80}")
        print("Complete scraping finished!")
        print(f"{'='*80}")
        print(f"Total items scraped: {len(all_results)}")

        return all_results
    
    def export_to_excel(self, all_results, filename=None):
        """Export results to Excel with complete data"""
        if not all_results:
            print("No data to export")
            return None
        
        try:
            if not filename:
                filename = f"complete_dining_data_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
            
            # Create DataFrame
            df = pd.DataFrame(all_results)

            # Sort by dining_hall, service, date, meal_type, name
            df = df.sort_values(['dining_hall', 'service', 'date', 'meal_type', 'name'],
                                ascending=[True, True, True, True, True])

            # Reorder columns to include date and meal_type
            column_order = [
                'dining_hall', 'service', 'date', 'meal_type', 'category', 'name', 'traits', 'serving_size',
                'calories', 'total_fat', 'saturated_fat', 'trans_fat', 'cholesterol',
                'sodium', 'potassium', 'total_carbohydrate', 'dietary_fiber', 'sugars', 'protein'
            ]
            # Only keep columns that actually exist in df to avoid KeyError
            column_order = [c for c in column_order if c in df.columns]
            df = df[column_order]
            
            # Write to Excel
            with pd.ExcelWriter(filename, engine='openpyxl') as writer:
                df.to_excel(writer, sheet_name='Complete Data', index=False)
                
                workbook = writer.book
                worksheet = writer.sheets['Complete Data']
                
                # Auto-adjust columns
                for column in worksheet.columns:
                    max_length = 0
                    column_letter = column[0].column_letter
                    
                    for cell in column:
                        try:
                            if len(str(cell.value)) > max_length:
                                max_length = len(str(cell.value))
                        except:
                            pass
                    
                    adjusted_width = min(max_length + 2, 50)
                    worksheet.column_dimensions[column_letter].width = adjusted_width
                
                # Format headers
                from openpyxl.styles import Font, PatternFill, Alignment
                
                header_fill = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
                header_font = Font(bold=True, color="FFFFFF")
                
                for cell in worksheet[1]:
                    cell.fill = header_fill
                    cell.font = header_font
                    cell.alignment = Alignment(horizontal="center", vertical="center")

            print(f"Exported to {filename}")
            print(f"Total rows: {len(df)}")

            # Summary statistics
            print("\nData Summary:")
            print(f"  Unique dining halls: {df['dining_hall'].nunique()}")
            if 'date' in df.columns:
                print(f"  Unique dates: {df['date'].nunique()}")
            if 'meal_type' in df.columns:
                print(f"  Unique meal types: {df['meal_type'].nunique()}")
            if 'category' in df.columns:
                print(f"  Unique categories: {df['category'].nunique()}")
            
            return filename
            
        except Exception as e:
            print(f"Error exporting to Excel: {str(e)}")
            import traceback
            traceback.print_exc()
            return None
    
    def close(self):
        """Close the browser"""
        self.driver.quit()


if __name__ == "__main__":
    # Set testing_mode=False for full scraping
    TESTING_MODE = False

    # Number of days to scrape (including today)
    DAYS_TO_SCRAPE = 7

    scraper = NutritionScraperComplete(testing_mode=TESTING_MODE)

    try:
        print("\n" + "="*80)
        if TESTING_MODE:
            print("RUNNING IN TESTING MODE")
            print("- Will scrape only 5 items per meal")
            print("- Consider limiting dining halls and meals for faster testing")
        else:
            print(f"FULL SCRAPING MODE - {DAYS_TO_SCRAPE} Days")
            print("- Will scrape all dining halls and services")
            print("- Will scrape all menu items")
            print(f"- Will scrape menus for the next {DAYS_TO_SCRAPE} days (including today)")
        print("="*80 + "\n")

        all_results = scraper.scrape_all_with_complete_data(days_to_scrape=DAYS_TO_SCRAPE)
        
        if all_results:
            print(f"\n{'='*80}")
            print("Final Results Summary")
            print(f"{'='*80}")
            
            # Summary statistics
            unique_halls = set(r['dining_hall'] for r in all_results)
            unique_dates = set(r['date'] for r in all_results if r.get('date'))
            unique_meals = set(r['meal_type'] for r in all_results if r.get('meal_type'))
            unique_categories = set(r['category'] for r in all_results if r.get('category'))

            print(f"Total items: {len(all_results)}")
            print(f"Dining halls: {len(unique_halls)}")
            print(f"Dates covered: {', '.join(sorted(unique_dates))}")
            print(f"Meal types: {', '.join(sorted(unique_meals))}")
            print(f"Categories: {len(unique_categories)}")

            # Export
            print(f"\nExporting complete data...")
            excel_file = scraper.export_to_excel(all_results)

            if excel_file:
                print(f"\n✓ Success! Excel file: {excel_file}")

            # Sample output
            print(f"\nSample items:")
            for r in all_results[:5]:
                print(f"  • {r['name']} [{r['category']}] ({r['meal_type']}) - {r['calories']} cal")
            
        else:
            print("No data scraped")
    
    except KeyboardInterrupt:
        print("\n\nInterrupted by user")
    except Exception as e:
        print(f"\nError: {str(e)}")
        import traceback
        traceback.print_exc()
    finally:
        scraper.close()
        print("Browser closed.")