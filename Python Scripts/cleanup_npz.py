import os
import glob

# Path to the directory containing scenarios
search_dir = r"C:\Users\domin\Documents\Web Scripts\Starlink Radar\SAR Sim Results Image and Video"

print(f"Searching for .npz files in: {search_dir}")

# Use glob to find all .npz files recursively
npz_files = glob.glob(os.path.join(search_dir, "**", "*.npz"), recursive=True)

total_freed = 0
deleted_count = 0

for file_path in npz_files:
    try:
        size = os.path.getsize(file_path)
        os.remove(file_path)
        total_freed += size
        deleted_count += 1
        print(f"Deleted: {file_path} ({size / (1024*1024):.2f} MB)")
    except Exception as e:
        print(f"Error deleting {file_path}: {e}")

print("-------------------------------------------------")
print(f"Successfully deleted {deleted_count} .npz files.")
print(f"Total space freed: {total_freed / (1024*1024*1024):.2f} GB")
print("-------------------------------------------------")
