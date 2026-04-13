import pandas as pd
import os

# Read the CSV
df = pd.read_csv('ecommerce/data/products.csv')

print("\n🔍 CHECKING IMAGE ISSUES:")
print("=" * 80)

# Check each category
for cat in df['category'].unique():
    cat_df = df[df['category'] == cat]
    
    # Count different URL types
    base64_count = cat_df['image_url'].astype(str).str.startswith('data:image').sum()
    unsplash_count = cat_df['image_url'].astype(str).str.contains('unsplash').sum()
    broken_count = cat_df['image_url'].astype(str).str.contains('loremflickr|poojaelectronics|gstatic|encrypted-tbn').sum()
    
    print(f"\n{cat}:")
    print(f"  ✓ Base64 images: {base64_count}")
    print(f"  ✓ Unsplash URLs: {unsplash_count}")
    print(f"  ✗ Broken/External URLs: {broken_count}")
    
    if broken_count > 0:
        # Show example of broken URL
        broken = cat_df[cat_df['image_url'].astype(str).str.contains('loremflickr|poojaelectronics|gstatic|encrypted-tbn', na=False)]['image_url'].head(1)
        if len(broken) > 0:
            print(f"  Example broken URL: {broken.values[0][:60]}...")

print("\n" + "=" * 80)
print("\n✓ IMAGE DIAGNOSTIC COMPLETE")
