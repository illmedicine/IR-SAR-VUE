import json
import os
import subprocess
import shutil

OUTPUT_ROOT = "SAR Sim Results Image and Video"

if not os.path.exists(OUTPUT_ROOT):
    os.makedirs(OUTPUT_ROOT)

scenarios = [
    {
        "name": "11v5_LFM_20kW_mBP_StdJet_9km_250ms",
        "cfg": { "waveform_type": "LFM", "tx_power_w": 20000.0, "num_wifi": 0, "num_towers": 0, "num_cars": 0, "num_jets": 1, "num_stealth_jets": 0, "jet_alt_m": 9000.0, "jet_vel_m_s": [250.0, 0.0, 0.0], "cpi_sec": 10.0, "max_target_alt_m": 9000.0 },
        "tdbp": { "v_tgt": [250.0, 0.0, 0.0], "z_focus": 9000.0, "scene_size": 1000.0, "nx": 1024, "ny": 1024 }
    },
    {
        "name": "12v5_LFM_20kW_mBP_Stealth_1km_250ms",
        "cfg": { "waveform_type": "LFM", "tx_power_w": 20000.0, "num_wifi": 0, "num_towers": 0, "num_cars": 0, "num_jets": 0, "num_stealth_jets": 1, "stealth_alt_m": 1000.0, "stealth_vel_m_s": [250.0, 0.0, 0.0], "cpi_sec": 10.0, "max_target_alt_m": 1500.0 },
        "tdbp": { "v_tgt": [250.0, 0.0, 0.0], "z_focus": 1500.0, "scene_size": 1000.0, "nx": 1024, "ny": 1024 }
    },
    {
        "name": "13v5_LFM_20kW_mBP_Stealth_9km_Mach1.5",
        "cfg": { "waveform_type": "LFM", "tx_power_w": 20000.0, "num_wifi": 0, "num_towers": 0, "num_cars": 0, "num_jets": 0, "num_stealth_jets": 1, "stealth_alt_m": 9000.0, "stealth_vel_m_s": [510.0, 0.0, 0.0], "cpi_sec": 10.0, "max_target_alt_m": 9500.0 },
        "tdbp": { "v_tgt": [510.0, 0.0, 0.0], "z_focus": 9500.0, "scene_size": 1000.0, "nx": 1024, "ny": 1024 }
    }
]

for s in scenarios:
    s["cfg"]["num_clutter_pts"] = 0
    s["cfg"]["earth_rotation_mode"] = "none"
    s_name = s["name"]
    print(f"\n{'='*60}\nRUNNING SCENARIO: {s_name}\n{'='*60}")
    
    out_dir = os.path.join(OUTPUT_ROOT, s_name)
    if not os.path.exists(out_dir):
        os.makedirs(out_dir)
        
    s["tdbp"]["out_dir"] = out_dir
    s["cfg"]["out_dir"] = out_dir
        
    # 1. Update Physics Engine Config
    with open("batch_override.json", "w") as f:
        json.dump(s["cfg"], f, indent=4)
        
    # 2. Update TDBP Engine Config
    with open("tdbp_override.json", "w") as f:
        json.dump(s["tdbp"], f, indent=4)
        
    # Run Physics
    res = subprocess.run(["python", "sar_simulation_env.py"])
    if res.returncode != 0:
        print(f"FAILED Physics on {s_name}!")
        continue
        
    # Save modular parameters inside directory natively
    if os.path.exists("batch_override.json"):
        shutil.move("batch_override.json", os.path.join(out_dir, "cfg.json"))
        
    # Run Reconstruction Sequence (mBP Logic Overlapping sliding frames)
    res_tdbp = subprocess.run(["python", "sar_tdbp_mbp.py"])
    if res_tdbp.returncode != 0:
        print(f"FAILED mBP Reconstruction on {s_name}!")
        continue
    
    print(f"Successfully processed {s_name}! Results safely deposited.")

print("\nAll Scenarios Processed Correctly Nightly Automation Complete!")
