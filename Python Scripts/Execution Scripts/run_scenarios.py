import subprocess
import os
import shutil
import time

scenarios = [
    {
        "name": "Scenario_1_5km_Scene_Baseline",
        "area_size": "5000",
        "scatter_area": "5000",
        "emitters": "2"
    }
]

out_dir = "SIGINT Sim Results"
brain_dir = r"C:\Users\domin\.gemini\antigravity\brain\bfc6c96a-2f36-482b-b0e7-a1b1b7179568"

for i, sc in enumerate(scenarios):
    print(f"\n======================================")
    print(f" EXEC: {sc['name']}")
    print(f"======================================")
    
    cmd1 = ["python", "sigint_sim_env.py", "--emitters", sc['emitters'], "--scatter_area", sc['scatter_area'], "--area_size", sc['area_size']]
    res1 = subprocess.run(cmd1)
    if res1.returncode != 0:
        print(f"Failed simulation for {sc['name']}. Exiting.")
        break
        
    cmd2 = ["python", "sigint_multibeam_processing.py"]
    res2 = subprocess.run(cmd2)
    if res2.returncode != 0:
        print(f"Failed processing for {sc['name']}. Exiting.")
        break
        
    # 3. Rename and move ALL mappings smoothly seamlessly into Native Subdirectories!
    import glob
    scenario_dir = os.path.join(out_dir, sc['name'])
    os.makedirs(scenario_dir, exist_ok=True)
    
    for png in glob.glob(os.path.join(out_dir, "*.png")):
        base = os.path.basename(png)
        if base == "city_view.png":
            # Just copy this one so it stays in root too
            shutil.copy(png, os.path.join(scenario_dir, base))
            continue
        dest_file = os.path.join(scenario_dir, base)
        shutil.move(png, dest_file) # Move it out of root explicitly cleanly
        print(f"Moved exactly identically cleanly dynamically to -> {dest_file}")
        
    for npz in glob.glob(os.path.join(out_dir, "*.npz")):
        shutil.copy(npz, os.path.join(scenario_dir, os.path.basename(npz)))
        
print("\nAll Scenarios Successfully Complete!")
