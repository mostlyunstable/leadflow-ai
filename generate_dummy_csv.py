import csv
import random
import os

# Create dummy leads for testing
dummy_data = [
    {"First Name": "Alice", "Last Name": "Smith", "Email": "alice.smith@example.com", "Company Name": "TechNova Solutions", "Website": "https://example.com/technova", "Industry": "Software"},
    {"First Name": "Bob", "Last Name": "Johnson", "Email": "bjohnson@example.net", "Company Name": "Global Logistics Inc", "Website": "", "Industry": "Logistics"},
    {"First Name": "Charlie", "Last Name": "Davis", "Email": "charlie@fakebusiness.org", "Company Name": "Green Energy Solutions", "Website": "https://example.org", "Industry": "Renewable Energy"},
    {"First Name": "Dana", "Last Name": "White", "Email": "dwhite@example.co", "Company Name": "Urban Architecture Labs", "Website": "https://example.co", "Industry": "Architecture"},
    {"First Name": "Evan", "Last Name": "Wright", "Email": "evan@example.io", "Company Name": "NextGen AI", "Website": "", "Industry": "Artificial Intelligence"},
]

output_file = "dummy_leads_test.csv"

def generate_csv():
    with open(output_file, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=["First Name", "Last Name", "Email", "Company Name", "Website", "Industry"])
        writer.writeheader()
        for row in dummy_data:
            writer.writerow(row)
    print(f"✅ Generated {len(dummy_data)} leads in '{output_file}'!")
    print("You can upload this file directly to your LeadFlow AI dashboard to test the pipeline.")

if __name__ == "__main__":
    generate_csv()
