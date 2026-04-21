import json
import os
import subprocess
import shutil
import copy

OUTPUT_ROOT = "SAR Sim Results Image and Video"

def run_scenario(s):
    s_name = s["name"]
    print(f"\n==================================\nRUNNING OVERNIGHT SWEEP: {s_name}\n==================================")
    out_dir = os.path.join(OUTPUT_ROOT, s_name)
    os.makedirs(out_dir, exist_ok=True)
    
    cfg = s["cfg"]
    cfg["out_dir"] = out_dir
    tdbp = s["tdbp"]
    tdbp["out_dir"] = out_dir
    
    with open("batch_override.json", "w") as f: json.dump(cfg, f, indent=4)
    with open("tdbp_override.json", "w") as f: json.dump(tdbp, f, indent=4)
    
    print("Running Physics...")
    res = subprocess.run(["python", "sar_simulation_env.py"])
    if res.returncode != 0: 
        print("Physics failed! Skipping...")
        return
    
    shutil.copy2("batch_override.json", os.path.join(out_dir, "cfg.json"))
    shutil.copy2("tdbp_override.json", os.path.join(out_dir, "tdbp_cfg.json"))
    
    print("Running Spotlight Recovery for static imagery...")
    subprocess.run(["python", "sar_tdbp_spotlight.py"])
    print(f"Finished {s_name}")

base_cfg = {
    "num_clutter_pts": 100, 
    "num_wifi": 0, 
    "num_towers": 0,
    "num_cars": 10,  # "stationary cars or something"
    "num_jets": 0, "num_stealth_jets": 0,
    "num_people_only": 0,            
    "tx_power_w": 20000.0, # The user was running 20kW earlier, I'll stick to a standard 20,000W or maybe 60W. Let's use 60W for standard Starlink radar testing.
    "cpi_sec": 5.0, # 5.0s is plenty for static spotlight resolution                  
    "earth_rotation_mode": "none",
    "area_size_m": [250, 250],        
    "ofdm_subcarrier_bw_hz": 200000.0,
    "bandwidth_hz": 500e6,
}

base_cfg["tx_power_w"] = 60.0 # Standard radar power

base_tdbp = {
    "scene_size": 250.0,
    "nx": 1024, "ny": 1024, # High res imagery for evaluation
    "enable_video": False,
    "enable_change_detection": False
}

jammers = [
    {"watts": 1, "dbm": 30.0, "bw_hz": 10e6},
    {"watts": 10, "dbm": 40.0, "bw_hz": 20e6},
    {"watts": 100, "dbm": 50.0, "bw_hz": 100e6},
    {"watts": 1000, "dbm": 60.0, "bw_hz": 200e6},
    {"watts": 10000, "dbm": 70.0, "bw_hz": 400e6},
    {"watts": 100000, "dbm": 80.0, "bw_hz": 450e6}
]

envs = []
for j in jammers:
    w = j["watts"]
    dbm = j["dbm"]
    bw = j["bw_hz"]
    bw_mhz = int(bw / 1e6)
    
    # Random realistic center frequency inside the 1750-2250MHz range for OFDM to notch
    cf_hz = 2.0e9 # Center the jammer right in the middle of our 2 GHz radar
    
    # 1. LFM without EMI (baseline for comparison, only need it once, but we can do it for every power just to be robust)
    envs.append({
        "name": f"I_{w}W_{bw_mhz}MHz_LFM_Clean",
        "cfg": {**base_cfg, "waveform_type": "LFM", "num_inband_emitters": 0},
        "tdbp": copy.deepcopy(base_tdbp)
    })
    
    # 2. LFM WITH EMI
    envs.append({
        "name": f"I_{w}W_{bw_mhz}MHz_LFM_Jammed",
        "cfg": {
            **base_cfg, 
            "waveform_type": "LFM", 
            "num_inband_emitters": 1, # Just one massive jammer is enough as specified
            "tx_power_dbm_override": dbm,
            "bandwidth_hz_override": bw,
            "center_freq_hz_override": cf_hz
        },
        "tdbp": copy.deepcopy(base_tdbp)
    })
    
    # 3. OFDM WITH EMI (Nulled)
    envs.append({
        "name": f"I_{w}W_{bw_mhz}MHz_OFDM_Nulled",
        "cfg": {
            **base_cfg, 
            "waveform_type": "OFDM", 
            "num_inband_emitters": 1,
            "tx_power_dbm_override": dbm,
            "bandwidth_hz_override": bw,
            "center_freq_hz_override": cf_hz
        },
        "tdbp": copy.deepcopy(base_tdbp)
    })

# Run the giant overnight sweep
for e in envs:
    run_scenario(e)
