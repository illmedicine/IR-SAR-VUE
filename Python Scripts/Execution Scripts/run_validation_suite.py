import json
import os
import subprocess
import shutil

OUTPUT_ROOT = "SAR Sim Results Image and Video"

def run_scenario(s_name, cfg, tdbp):
    print(f"\n{'='*60}\nRUNNING SCENARIO: {s_name}\n{'='*60}")
    
    out_dir = os.path.join(OUTPUT_ROOT, s_name)
    os.makedirs(out_dir, exist_ok=True)
    
    cfg["out_dir"] = out_dir
    tdbp["out_dir"] = out_dir
    
    with open("batch_override.json", "w") as f:
        json.dump(cfg, f, indent=4)
    with open("tdbp_override.json", "w") as f:
        json.dump(tdbp, f, indent=4)
        
    print("Running Physics...")
    res = subprocess.run(["python", "sar_simulation_env.py"])
    if res.returncode != 0:
        print(f"FAILED Physics on {s_name}!")
        return False
        
    shutil.copy2("batch_override.json", os.path.join(out_dir, "cfg.json"))
    shutil.copy2("tdbp_override.json", os.path.join(out_dir, "tdbp_cfg.json"))
    
    print("Running Spotlight Recovery...")
    res_tdbp = subprocess.run(["python", "sar_tdbp_spotlight.py"])
    if res_tdbp.returncode != 0:
        print(f"FAILED Spotlight Reconstruction on {s_name}!")
        return False
        
    print(f"Successfully processed {s_name}!")
    return True

# 1. First, Re-run H3 with Humans and Video
h3_name = "H3_Humans_Moving_Video_OFDM_EMI_Nulling"
h3_cfg = {
    "waveform_type": "OFDM",
    "tx_power_w": 60.0,
    "cpi_sec": 10.0,
    "earth_rotation_mode": "none",
    "num_clutter_pts": 100,
    "num_wifi": 4,
    "num_towers": 2,
    "num_inband_emitters": 14,
    "num_cars": 0,
    "num_jets": 0,
    "num_stealth_jets": 0,
    "num_people_only": 7,     # Moving Targets
    "area_size_m": [500, 500],
    "ofdm_subcarrier_bw_hz": 200000.0,
    "ofdm_null_bands": []
}

h3_tdbp = {
    "scene_size": 500.0,
    "nx": 1024, "ny": 1024,
    "enable_video": True,
    "video_cpi": 0.5,
    "video_fps": 5,
    "video_duration": 5.0,
    "enable_change_detection": False
}

run_scenario(h3_name, h3_cfg, h3_tdbp)

# 2. Iterate through 06-08 and C4-C6 folders and OVERWRITE them with exactly the identical setups using new OFDM
scenarios_to_restart = [
    "06_OFDM_15kHz_20kW_NoEmi_NoJets",
    "07_OFDM_60kHz_20kW_NoEmi_NoJets",
    "08_OFDM_200kHz_20kW_NoEmi_NoJets",
    "C4_OFDM_2MHz_MaxRes_50m_4pts",
    "C5_OFDM_15kHz_MaxRes_50m_4pts",
    "C6_OFDM_200kHz_MaxRes_50m_4pts"
]

for s in scenarios_to_restart:
    cfg_path = os.path.join(OUTPUT_ROOT, s, "cfg.json")
    tdbp_path = os.path.join(OUTPUT_ROOT, s, "tdbp_cfg.json")
    
    if os.path.exists(cfg_path) and os.path.exists(tdbp_path):
        with open(cfg_path, "r") as f:
            cfg = json.load(f)
        with open(tdbp_path, "r") as f:
            tdbp = json.load(f)
            
        # Re-run it
        run_scenario(s, cfg, tdbp)
    else:
        print(f"Skipping {s} because cfg arrays were missing!")
