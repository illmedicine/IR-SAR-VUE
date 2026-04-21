import json
import os
import subprocess
import shutil

OUTPUT_ROOT = "SAR Sim Results Image and Video"

def run_scenario(s_name, processor, cfg, tdbp):
    print(f"\n==================================\nRUNNING SCENARIO: {s_name}\n==================================")
    out_dir = os.path.join(OUTPUT_ROOT, s_name)
    os.makedirs(out_dir, exist_ok=True)
    cfg["out_dir"] = out_dir
    tdbp["out_dir"] = out_dir
    
    with open("batch_override.json", "w") as f: json.dump(cfg, f, indent=4)
    with open("tdbp_override.json", "w") as f: json.dump(tdbp, f, indent=4)
    
    print("Running Physics...")
    subprocess.run(["python", "sar_simulation_env.py"])
    
    shutil.copy2("batch_override.json", os.path.join(out_dir, "cfg.json"))
    shutil.copy2("tdbp_override.json", os.path.join(out_dir, "tdbp_cfg.json"))
    
    proc_script = "sar_tdbp_mbp.py" if processor == "mbp" else "sar_tdbp_spotlight.py"
    print(f"Running {proc_script}...")
    subprocess.run(["python", proc_script])
    print(f"Finished {s_name}")

scenarios = [
    {
        "name": "F_Warhead_100km_Mach10_mBP",
        "processor": "mbp",
        "cfg": {
            "waveform_type": "LFM", "bandwidth_hz": 500e6,
            "sar_mode": "spotlight", 
            "tx_power_w": 20000.0, "cpi_sec": 10.0,
            "num_warheads": 1, "warhead_alt_m": 100000.0, "warhead_vel_m_s": [3430.0, 0.0, 0.0],
            "num_clutter_pts": 0, "num_cars": 0, "num_people_only": 0, "num_inband_emitters": 0,
            "scene_alt_m": 100000.0,
            "area_size_m": [1000, 1000], "earth_rotation_mode": "none"
        },
        "tdbp": {
            "scene_size": 2000.0, "nx": 1024, "ny": 1024,
            "z_focus": 100000.0, "v_tgt": [3430.0, 0.0, 0.0], "center_mode": "midpoint",
            "enable_video": True, "enable_change_detection": True, "video_cpi": 0.5, "video_fps": 5, "video_duration": 10.0
        }
    }
]

for s in scenarios:
    run_scenario(s["name"], s["processor"], s["cfg"], s["tdbp"])
