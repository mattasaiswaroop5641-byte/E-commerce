#!/usr/bin/env python3
"""
Fix image URLs for all non-mobile products in products.csv
Uses Unsplash URLs with relevant search terms for each product category
"""

import csv
import os
import sys

# Set encoding to UTF-8
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

    # Unsplash image URLs by category - using relevant search terms
CATEGORY_IMAGES = {
    'Electronics': [
        'https://images.unsplash.com/photo-1505228395891-9a51e7e86e81?auto=format&fit=crop&w=720&h=720&q=80',
        'https://images.unsplash.com/photo-1517694712202-14dd9538aa97?auto=format&fit=crop&w=720&h=720&q=80',
        'https://images.unsplash.com/photo-1496181133206-80ce9b88a853?auto=format&fit=crop&w=720&h=720&q=80',
        'https://images.unsplash.com/photo-1523275335684-37898b6baf30?auto=format&fit=crop&w=720&h=720&q=80',
    ],
    'Fashion': [
        'https://images.unsplash.com/photo-1521572163474-6864f9cf17ab?auto=format&fit=crop&w=720&h=720&q=80',
        'https://images.unsplash.com/photo-1539533057440-7ce297ca0ed0?auto=format&fit=crop&w=720&h=720&q=80',
        'https://images.unsplash.com/photo-1556821552-9f6db051b1da?auto=format&fit=crop&w=720&h=720&q=80',
        'https://images.unsplash.com/photo-1589365278144-f217eef11848?auto=format&fit=crop&w=720&h=720&q=80',
    ],
    'Beauty & Personal Care': [
        'https://images.unsplash.com/photo-1556228578-8c89e6aef883?auto=format&fit=crop&w=720&h=720&q=80',
        'https://images.unsplash.com/photo-1596462502278-af242a95ab13?auto=format&fit=crop&w=720&h=720&q=80',
        'https://images.unsplash.com/photo-1540189549336-e6e99c3679fe?auto=format&fit=crop&w=720&h=720&q=80',
        'https://images.unsplash.com/photo-1494790108377-be9c29b29330?auto=format&fit=crop&w=720&h=720&q=80',
    ],
    'Home & Kitchen': [
        'https://images.unsplash.com/photo-1556909114-f6e7ad7d3136?auto=format&fit=crop&w=720&h=720&q=80',
        'https://images.unsplash.com/photo-1540189549336-e6e99c3679fe?auto=format&fit=crop&w=720&h=720&q=80',
        'https://images.unsplash.com/photo-1556228016-8ac196b43055?auto=format&fit=crop&w=720&h=720&q=80',
        'https://images.unsplash.com/photo-1578500494198-246f612d03b3?auto=format&fit=crop&w=720&h=720&q=80',
    ],
    'Sports & Fitness': [
        'https://images.unsplash.com/photo-1517836357463-d25ddfcbf042?auto=format&fit=crop&w=720&h=720&q=80',
        'https://images.unsplash.com/photo-1506920917128-3aa500764cbd?auto=format&fit=crop&w=720&h=720&q=80',
        'https://images.unsplash.com/photo-1461896836934-ffe607ba8211?auto=format&fit=crop&w=720&h=720&q=80',
        'https://images.unsplash.com/photo-1571902943202-507ec2618e8f?auto=format&fit=crop&w=720&h=720&q=80',
    ],
    'Books': [
        'https://images.unsplash.com/photo-1507842217343-583f20270319?auto=format&fit=crop&w=720&h=720&q=80',
        'https://images.unsplash.com/photo-1512820790803-83ca734da794?auto=format&fit=crop&w=720&h=720&q=80',
        'https://images.unsplash.com/photo-1543002588-d83cea6081cd?auto=format&fit=crop&w=720&h=720&q=80',
        'https://images.unsplash.com/photo-1506880018603-83d5b814b5a6?auto=format&fit=crop&w=720&h=720&q=80',
    ],
    'Toys & Games': [
        'https://images.unsplash.com/photo-1589465468171-41924e2b8526?auto=format&fit=crop&w=720&h=720&q=80',
        'https://images.unsplash.com/photo-1612872087720-bb876e2e67d1?auto=format&fit=crop&w=720&h=720&q=80',
        'https://images.unsplash.com/photo-1515934328302-c8c93ff92f5a?auto=format&fit=crop&w=720&h=720&q=80',
        'https://images.unsplash.com/photo-1484480974693-6ca0a78fb36b?auto=format&fit=crop&w=720&h=720&q=80',
    ],
    'Mobiles': [
        'https://images.unsplash.com/photo-1511707171634-5f897ff02aa9?auto=format&fit=crop&w=720&h=720&q=80',
        'https://images.unsplash.com/photo-1611707267537-b85faf00021a?auto=format&fit=crop&w=720&h=720&q=80',
        'https://images.unsplash.com/photo-1598327105666-5b89351aff97?auto=format&fit=crop&w=720&h=720&q=80',
        'https://images.unsplash.com/photo-1592286927505-1def25e5cefd?auto=format&fit=crop&w=720&h=720&q=80',
    ],
}

def fix_product_images():
    csv_path = 'ecommerce/data/products.csv'
    
    # Read all products
    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    
    # Track which products we update
    updated_count = 0
    category_counters = {}
    
    # Process each product
    for row in rows:
        category = row['category']
        product_name = row['name'][:30]
        
        # Fix all three image URL columns: thumb_image_url, hero_image_url, image_url
        for url_column in ['thumb_image_url', 'hero_image_url', 'image_url']:
            current_url = row[url_column].strip()
            # Replace if it has loremflickr placeholder OR is empty/mobile
            if 'loremflickr.com' in current_url or not current_url or current_url == 'mobile':
                # Rotate through available URLs for this category
                if category not in category_counters:
                    category_counters[category] = 0
                
                if category in CATEGORY_IMAGES:
                    urls = CATEGORY_IMAGES[category]
                    new_url = urls[category_counters[category] % len(urls)]
                    row[url_column] = new_url
                    category_counters[category] += 1
                    updated_count += 1
                    print(f"[+] Updated {category:25} {url_column:15} {product_name}")
    
    # Write back to CSV
    with open(csv_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=reader.fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    
    print(f"\n✅ Updated {updated_count} product image URLs")
    print(f"\nCategory breakdown:")
    for cat in sorted(category_counters.keys()):
        print(f"  {cat}: {category_counters[cat]} products")

if __name__ == '__main__':
    fix_product_images()
    print("\n✅ All non-mobile product images have been fixed!")
