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

base_cfg = {
    "sar_mode": "spotlight",
    "cpi_sec": 5.0,
    "bandwidth_hz": 500e6,
    "tx_power_w": 20000.0,
    "area_size_m": [40.0, 40.0],
    "scene_center_m": [0.0, 0.0, 0.0],
    "num_clutter_pts": 4,
    "num_wifi": 0,
    "num_towers": 0,
    "num_cars": 0,
    "num_jets": 0,
    "num_stealth_jets": 0,
    "num_warheads": 0,
    "num_people_only": 0,
    "num_inband_emitters": 0,
    "earth_rotation_mode": "none"
}

tdbp_cfg = {
    "scene_size": 50.0,
    "nx": 334, "ny": 334,
    "enable_video": False,
    "enable_change_detection": False
}

scenarios = [
    ("C1_LFM_MaxRes_50m_4pts", {"waveform_type": "LFM"}),
    ("C2_NLFM_MaxRes_50m_4pts", {"waveform_type": "NLFM"}),
    ("C3_PhaseCoded_MaxRes_50m_4pts", {"waveform_type": "PhaseCoded"}),
    ("C4_OFDM_15kHz_MaxRes_50m_4pts", {"waveform_type": "OFDM", "ofdm_subcarrier_bw_hz": 15000.0}),
    ("C5_OFDM_60kHz_MaxRes_50m_4pts", {"waveform_type": "OFDM", "ofdm_subcarrier_bw_hz": 60000.0}),
    ("C6_OFDM_200kHz_MaxRes_50m_4pts", {"waveform_type": "OFDM", "ofdm_subcarrier_bw_hz": 200000.0})
]

for s, s_cfg in scenarios:
    cfg = base_cfg.copy()
    cfg.update(s_cfg)
    run_scenario(s, cfg, tdbp_cfg.copy())
