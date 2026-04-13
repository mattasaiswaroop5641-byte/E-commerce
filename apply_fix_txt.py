#!/usr/bin/env python3
"""
Applies the image URLs from fix.txt directly to the products.csv database.
"""
import csv
import os
import re

def normalize_name(name):
    """Normalize product name keys for matching against fix mappings."""
    return re.sub(r"\s+", " ", str(name).strip().lower())

def main():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    fix_path = os.path.join(base_dir, "fix.txt")
    csv_path = os.path.join(base_dir, "ecommerce", "data", "products.csv")

    if not os.path.exists(fix_path):
        print(f"Error: {fix_path} not found.")
        return

    if not os.path.exists(csv_path):
        print(f"Error: {csv_path} not found.")
        return

    # Load fix.txt mappings
    mappings = {}
    with open(fix_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or ":" not in line:
                continue
            name, url = line.split(":", 1)
            mappings[normalize_name(name)] = url.strip()

    print(f"Loaded {len(mappings)} image mappings from fix.txt")

    # Read products.csv
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        if not fieldnames:
            print(f"Error: {csv_path} is empty or missing headers.")
            return
        rows = list(reader)

    # Update rows
    updated_count = 0
    for row in rows:
        base_name = normalize_name(row["name"])
        full_name = normalize_name(f"{row['name']} - {row['variant_label']}") if row.get("variant_label") else base_name
        
        # Match against exact variant name first, then fallback to base family name
        matched_url = mappings.get(full_name) or mappings.get(base_name)
        if matched_url:
            row["thumb_image_url"] = matched_url
            row["hero_image_url"] = matched_url
            row["image_url"] = matched_url
            updated_count += 1

    # Save products.csv
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"Successfully updated {updated_count} products in products.csv")

if __name__ == "__main__":
    main()