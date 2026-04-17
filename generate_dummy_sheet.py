import csv
import random

# Data pools for generating realistic-looking dummy leads
first_names = ["James", "Mary", "Robert", "Patricia", "John", "Jennifer", "Michael", "Linda", "William", "Elizabeth", "David", "Barbara", "Richard", "Susan", "Joseph", "Jessica", "Thomas", "Sarah", "Charles", "Karen"]
last_names = ["Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis", "Rodriguez", "Martinez", "Hernandez", "Lopez", "Gonzalez", "Wilson", "Anderson", "Thomas", "Taylor", "Moore", "Jackson", "Martin"]
industries = ["SaaS", "FinTech", "HealthTech", "E-commerce", "AI & Robotics", "Renewable Energy", "Real Estate", "Cybersecurity", "Digital Marketing", "Logistics", "EdTech", "Venture Capital"]
company_suffixes = ["Tech", "Solutions", "Inc", "Labs", "Group", "Global", "Systems", "Partners", "Co", "Ventures"]

leads = []
for i in range(50):
    first = random.choice(first_names)
    last = random.choice(last_names)
    industry = random.choice(industries)
    company_name = f"{last} {random.choice(company_suffixes)}"
    email = f"{first.lower()}.{last.lower()}@{company_name.lower().replace(' ', '')}.com"
    website = f"https://www.{company_name.lower().replace(' ', '')}.com"
    
    leads.append({
        "First Name": first,
        "Last Name": last,
        "Email": email,
        "Company Name": company_name,
        "Website": website,
        "Industry": industry
    })

# Write to CSV
with open('leads_for_google_sheets.csv', mode='w', newline='') as f:
    writer = csv.DictWriter(f, fieldnames=["First Name", "Last Name", "Email", "Company Name", "Website", "Industry"])
    writer.writeheader()
    writer.writerows(leads)

print(f"Successfully generated 50 dummy leads in leads_for_google_sheets.csv")
