import pandas as pd

# Read products CSV
df = pd.read_csv('ecommerce/data/products.csv')

# GoPro base64 image
gopro_base64 = 'data:image/jpeg;base64,/9j/4AAQSkZJRgABAQAAAQABAAD/2wCEAAkGBxISEhUTEhMVFRUVFRUVFRUWFRUWFxUWFRUWFxUXExMYHSggGBolGxUVITEhJSkrLi4uFx8zODMtNygtLisBCgoKDg0OGxAQGzAlHyYtLS0tLzIyLS0tLS0tLS0tNS0tLS0tLS0tLS0tLS0vLy0tLS0vLS0tKy05LS0tLS0tLS0tLf/AABEIANcA6gMBIgACEQEDEAH/xAAcAAEAAQUBAQAAAAAAAAAAAAAABgIDBAUHCAH/'

# Find and fix all GoPro products with broken URLs
fixed_count = 0

for idx, row in df.iterrows():
    if pd.isna(row['image_url']):
        continue
    
    img_url = str(row['image_url'])
    product_name = str(row['name']).lower()
    
    # Check if it's a GoPro with poojaelectronics URL (broken)
    if 'gopro' in product_name and 'poojaelectronics' in img_url:
        print(f"Fixing: {row['name']}")
        df.loc[idx, 'image_url'] = gopro_base64
        df.loc[idx, 'thumb_image_url'] = gopro_base64
        df.loc[idx, 'hero_image_url'] = gopro_base64
        fixed_count += 1

# Save
df.to_csv('ecommerce/data/products.csv', index=False)
print(f"\n✓ Fixed {fixed_count} GoPro products")
