from __future__ import print_function
import africastalking
from flask import Flask, request
import sqlite3
from datetime import datetime

app = Flask(__name__)

# Initialize Africa's Talking
username = "YOUR_USERNAME"
api_key = "YOUR_API_KEY"
africastalking.initialize(username, api_key)
sms = africastalking.SMS

def init_db():
    conn = sqlite3.connect("food_waste.db")
    c = conn.cursor()

    # Users table
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            phone_number TEXT PRIMARY KEY,
            user_type TEXT,
            name TEXT,
            location TEXT,
            waste_types TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """
    )

    # Waste listings table
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS waste_listings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            supplier_phone TEXT,
            waste_type TEXT,
            quantity FLOAT,
            available_until TIMESTAMP,
            status TEXT DEFAULT 'available',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """
    )

    conn.commit()
    conn.close()

@app.route("/ussd", methods=["POST"])
def ussd():
    # Read the variables sent via POST from our API
    phone_number = request.values.get("phoneNumber", None)
    text = request.values.get("text", "default")

    if text == "":
        # This is the first request. Note how we start the response with CON
        response = "CON Welcome to Food Waste Management\n"
        response += "1. Register as Food Waste Supplier\n"
        response += "2. Register as Food Waste Collector\n"
        response += "3. Request Food Waste Pickup\n"
        response += "4. Offer Available Food Waste\n"
        response += "5. Check Collection Locations\n"
        response += "6. View Pricing Options\n"  # New option for pricing
        return response

    elif text == "1" or text == "2":
        # Registration for supplier or collector
        response = "CON Enter your full name"
        return response

    elif text.startswith("1*") or text.startswith("2*"):
        parts = text.split("*")
        if len(parts) == 2:
            # Got name, ask for location
            return "CON Enter your location"
        elif len(parts) == 3:
            # Got location, ask for waste types
            if parts[0] == "1":
                return "CON Select waste types (comma-separated):\n1. Vegetable scraps\n2. Fruit peels\n3. Prepared food"
            else:
                return "CON Select feed types needed (comma-separated):\n1. Pig feed\n2. Poultry feed\n3. Rabbit feed"
        elif len(parts) == 4:
            # Final registration step
            user_type = "supplier" if parts[0] == "1" else "collector"
            name = parts[1]
            location = parts[2]
            waste_types = parts[3]

            conn = sqlite3.connect("food_waste.db")
            c = conn.cursor()
            
            # Check if the user is already registered
            c.execute("SELECT * FROM users WHERE phone_number = ?", (phone_number,))
            existing_user = c.fetchone()
            if existing_user:
                return "END You are already registered!"

            c.execute(
                """
                INSERT INTO users (phone_number, user_type, name, location, waste_types)
                VALUES (?, ?, ?, ?, ?)
            """,
                (phone_number, user_type, name, location, waste_types),
            )
            conn.commit()
            conn.close()

            # Send confirmation SMS
            try:
                message = f"Welcome to Food Waste Management! You are registered as a {user_type}."
                response = sms.send([message], [phone_number])
                print(response)
            except Exception as e:
                print(f"Error sending SMS: {e}")

            return "END Registration successful! Check your SMS for more information."

    elif text == "3":
        # Request pickup - show available listings
        conn = sqlite3.connect("food_waste.db")
        c = conn.cursor()
        c.execute(
            """
            SELECT id, waste_type, quantity, location 
            FROM waste_listings 
            JOIN users ON waste_listings.supplier_phone = users.phone_number
            WHERE status = 'available'
            ORDER BY created_at DESC LIMIT 5
        """
        )
        listings = c.fetchall()
        conn.close()

        if not listings:
            return "END No waste listings available at the moment."

        response = "CON Available waste:\n"
        for i, listing in enumerate(listings, 1):
            response += f"{i}. {listing[1]} - {listing[2]}kg at {listing[3]}\n"
        return response

    elif text.startswith("3*"):
        # Handle pickup request
        parts = text.split("*")
        try:
            listing_index = int(parts[1]) - 1
            conn = sqlite3.connect("food_waste.db")
            c = conn.cursor()

            c.execute(
                """
                UPDATE waste_listings 
                SET status = 'scheduled' 
                WHERE id IN (
                    SELECT id FROM waste_listings 
                    WHERE status = 'available'
                    ORDER BY created_at DESC LIMIT 5
                )
                OFFSET ? LIMIT 1
            """,
                (listing_index,),
            )

            if c.rowcount > 0:
                conn.commit()
                response = (
                    "END Pickup scheduled successfully! Check your SMS for details."
                )
            else:
                response = "END Invalid selection or listing no longer available."

            conn.close()
            return response

        except (ValueError, IndexError):
            return "END Invalid selection."

    elif text == "4":
        # Offer waste
        return "CON Select waste type:\n1. Vegetable scraps\n2. Fruit peels\n3. Prepared food"

    elif text.startswith("4*"):
        parts = text.split("*")
        if len(parts) == 2:
            return "CON Enter quantity in kg:"
        elif len(parts) == 3:
            return "CON Enter available until (HH:MM):"
        elif len(parts) == 4:
            try:
                waste_types = ["vegetable scraps", "fruit peels", "prepared food"]
                waste_type = waste_types[int(parts[1]) - 1]
                quantity = float(parts[2])
                time = datetime.strptime(parts[3], "%H:%M")
                available_until = datetime.combine(datetime.now().date(), time.time())

                conn = sqlite3.connect("food_waste.db")
                c = conn.cursor()
                c.execute(
                    """
                    INSERT INTO waste_listings (supplier_phone, waste_type, quantity, available_until)
                    VALUES (?, ?, ?, ?)
                """,
                    (phone_number, waste_type, quantity, available_until),
                )

                # Notify collectors
                c.execute(
                    'SELECT phone_number FROM users WHERE user_type = "collector"'
                )
                collectors = c.fetchall()
                conn.commit()
                conn.close()

                # Send SMS notifications
                message = f"New waste listing: {quantity}kg of {waste_type} available until {parts[3]}"
                for collector in collectors:
                    try:
                        response = sms.send([message], [collector[0]])
                        print(response)
                    except Exception as e:
                        print(f"Error sending SMS: {e}")

                return "END Waste listing created successfully! Collectors will be notified."

            except ValueError:
                return "END Invalid input format."

    elif text == "5":
        # Check collection locations
        conn = sqlite3.connect("food_waste.db")
        c = conn.cursor()
        c.execute(
            """
            SELECT location, COUNT(*) as user_count,
            SUM(CASE WHEN user_type = 'supplier' THEN 1 ELSE 0 END) as suppliers,
            SUM(CASE WHEN user_type = 'collector' THEN 1 ELSE 0 END) as collectors
            FROM users GROUP BY location
        """
        )
        locations = c.fetchall()
        conn.close()

        if not locations:
            return "END No collection locations registered yet."

        response = "END Collection Locations:\n"
        for loc in locations:
            response += f"{loc[0]}: {loc[2]} suppliers, {loc[3]} collectors\n"
        return response

    elif text == "6":
        # View Pricing Options
        response = "CON Select a pricing option:\n"
        response += "1. 5 KG Ksh 2500\n"
        response += "2. 10 KG Ksh 9500\n"
        response += "3. 15 KG Ksh 15000\n"
        response += "4. 20 KG Ksh 20000\n"
        response += "5. 30 KG Ksh 30000\n"
        return response

    elif text.startswith("6*"):
        parts = text.split("*")
        if len(parts) == 2:
            pricing_options = {
                "1": "5 KG Ksh 2500",
                "2": "10 KG Ksh 9500",
                "3": "15 KG Ksh 15000",
                "4": "20 KG Ksh 20000",
                "5": "30 KG Ksh 300
