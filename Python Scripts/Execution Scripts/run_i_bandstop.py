import json
import os
import subprocess
import shutil
import copy

OUTPUT_ROOT = "SAR Sim Results Image and Video"

def run_scenario(s):
    s_name = s["name"]
    print(f"\n==================================\nRUNNING: {s_name}\n==================================")
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
    
    print("Running Spotlight Recovery...")
    subprocess.run(["python", "sar_tdbp_spotlight.py"])
    print(f"Finished {s_name}")

base_cfg = {
    "num_clutter_pts": 100, 
    "num_wifi": 0, 
    "num_towers": 0,
    "num_cars": 10,  
    "num_jets": 0, "num_stealth_jets": 0,
    "num_people_only": 0,            
    "tx_power_w": 60.0, 
    "cpi_sec": 5.0,                   
    "earth_rotation_mode": "none",
    "area_size_m": [250, 250],        
    "ofdm_subcarrier_bw_hz": 200000.0,
    "bandwidth_hz": 500e6,
}

base_tdbp = {
    "scene_size": 250.0,
    "nx": 1024, "ny": 1024, 
    "enable_video": False,
    "enable_change_detection": False
}

envs = []
cf_hz = 2.0e9

# --- 1. Evaluate OFDM Nulling + NATIVE RECEIVE BANDSTOP for the first 5 powers ---
jammers = [
    {"watts": 1, "dbm": 30.0, "bw_hz": 10e6},
    {"watts": 10, "dbm": 40.0, "bw_hz": 20e6},
    {"watts": 100, "dbm": 50.0, "bw_hz": 100e6},
    {"watts": 1000, "dbm": 60.0, "bw_hz": 200e6},
    {"watts": 10000, "dbm": 70.0, "bw_hz": 400e6}
]

for j in jammers:
    w = j["watts"]
    dbm = j["dbm"]
    bw = j["bw_hz"]
    bw_mhz = int(bw / 1e6)
    
    tdbp_bandstop = copy.deepcopy(base_tdbp)
    tdbp_bandstop["emi_notch_bands"] = [[cf_hz, bw]]  # Activate Native Spotlight Receive Nulling
    
    envs.append({
        "name": f"I_{w}W_{bw_mhz}MHz_OFDM_Nulled_Bandstop",
        "cfg": {
            **base_cfg, 
            "waveform_type": "OFDM", 
            "num_inband_emitters": 1,
            "tx_power_dbm_override": dbm,
            "bandwidth_hz_override": bw,
            "center_freq_hz_override": cf_hz
        },
        "tdbp": tdbp_bandstop
    })

# --- 2. Redo 100,000 W (which crashed previously) + Add its new Bandstop version ---
w = 100000
dbm = 80.0
bw = 450e6
bw_mhz = 450

# A) LFM Clean
envs.append({
    "name": f"I_{w}W_{bw_mhz}MHz_LFM_Clean",
    "cfg": {**base_cfg, "waveform_type": "LFM", "num_inband_emitters": 0},
    "tdbp": copy.deepcopy(base_tdbp)
})

# B) LFM Jammed
envs.append({
    "name": f"I_{w}W_{bw_mhz}MHz_LFM_Jammed",
    "cfg": {
        **base_cfg, 
        "waveform_type": "LFM", 
        "num_inband_emitters": 1, 
        "tx_power_dbm_override": dbm,
        "bandwidth_hz_override": bw,
        "center_freq_hz_override": cf_hz
    },
    "tdbp": copy.deepcopy(base_tdbp)
})

# C) OFDM Nulled (No Receive Bandstop)
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

# D) OFDM Nulled + Receive Bandstop
tdbp_100k_bandstop = copy.deepcopy(base_tdbp)
tdbp_100k_bandstop["emi_notch_bands"] = [[cf_hz, bw]]

envs.append({
    "name": f"I_{w}W_{bw_mhz}MHz_OFDM_Nulled_Bandstop",
    "cfg": {
        **base_cfg, 
        "waveform_type": "OFDM", 
        "num_inband_emitters": 1,
        "tx_power_dbm_override": dbm,
        "bandwidth_hz_override": bw,
        "center_freq_hz_override": cf_hz
    },
    "tdbp": tdbp_100k_bandstop
})

for e in envs:
    run_scenario(e)
