"""
Overnight SAR Batch Script v2
==============================
A1v2: Stationary mBP fighter jet (50m, center_mode=track)
B2:   Clutter only (500 clutter, no cars) — debug isolation
B3:   Cars only (50 cars, no clutter) — debug isolation
D:    Stealth 1km + 500 clutter mBP fly-under-radar + CD (physics already done)
"""

import json
import os
import subprocess
import shutil
import time

OUTPUT_ROOT = "SAR Sim Results Image and Video"
os.makedirs(OUTPUT_ROOT, exist_ok=True)

scenarios = [
    # --------------------------------------------------------
    # A1v2. Max-res mBP fighter jet STATIONARY (target stays centered)
    # --------------------------------------------------------
    {
        "name": "A1v2_MaxRes_mBP_Jet_Stationary_50m",
        "processor": "mbp",
        "cfg": {
            "waveform_type": "LFM",
            "tx_power_w": 20000.0,
            "num_wifi": 0, "num_towers": 0, "num_cars": 0,
            "num_jets": 1, "num_stealth_jets": 0,
            "jet_alt_m": 1000.0,
            "jet_vel_m_s": [250.0, 0.0, 0.0],
            "cpi_sec": 10.0,
            "max_target_alt_m": 1000.0,
            "num_clutter_pts": 0,
            "area_size_m": [50, 50],
        },
        "tdbp": {
            "v_tgt": [250.0, 0.0, 0.0],
            "z_focus": 1000.0,
            "scene_size": 50.0,
            "nx": 334, "ny": 334,
            "enable_change_detection": False,
            "center_mode": "track",
        }
    },
    # --------------------------------------------------------
    # B2. Clutter only (500 pts, no cars) — debug isolation
    # --------------------------------------------------------
    {
        "name": "B2_LFM_20kW_ClutterOnly_500pts",
        "processor": "spotlight",
        "cfg": {
            "waveform_type": "LFM",
            "tx_power_w": 20000.0,
            "num_wifi": 0, "num_towers": 0,
            "num_cars": 0,
            "num_jets": 0, "num_stealth_jets": 0,
            "cpi_sec": 10.0,
            "num_clutter_pts": 500,
            "area_size_m": [500, 500],
        },
        "tdbp": {
            "scene_size": 500.0,
            "nx": 1024, "ny": 1024,
            "enable_video": True,
            "video_cpi": 0.5,
            "video_fps": 5,
            "video_duration": 5.0,
            "enable_change_detection": True,
        }
    },
    # --------------------------------------------------------
    # B3. Cars only (50 cars, no clutter) — debug isolation
    # --------------------------------------------------------
    {
        "name": "B3_LFM_20kW_CarsOnly_50",
        "processor": "spotlight",
        "cfg": {
            "waveform_type": "LFM",
            "tx_power_w": 20000.0,
            "num_wifi": 0, "num_towers": 0,
            "num_cars": 50,
            "num_jets": 0, "num_stealth_jets": 0,
            "cpi_sec": 10.0,
            "num_clutter_pts": 0,
            "area_size_m": [500, 500],
        },
        "tdbp": {
            "scene_size": 500.0,
            "nx": 1024, "ny": 1024,
            "enable_video": True,
            "video_cpi": 0.5,
            "video_fps": 5,
            "video_duration": 5.0,
            "enable_change_detection": True,
        }
    },
    # --------------------------------------------------------
    # D. Stealth 1km + 500 clutter — fly under the radar + CD
    #    Physics already completed, skip_physics flag set
    # --------------------------------------------------------
    {
        "name": "D_Stealth_1km_FlyUnderRadar_CD",
        "processor": "mbp",
        "cfg": {
            "waveform_type": "LFM",
            "tx_power_w": 20000.0,
            "num_wifi": 0, "num_towers": 0, "num_cars": 0,
            "num_jets": 0, "num_stealth_jets": 1,
            "stealth_alt_m": 1000.0,
            "stealth_vel_m_s": [250.0, 0.0, 0.0],
            "cpi_sec": 10.0,
            "max_target_alt_m": 1500.0,
            "num_clutter_pts": 500,
            "area_size_m": [1000, 1000],
        },
        "tdbp": {
            "v_tgt": [250.0, 0.0, 0.0],
            "z_focus": 1500.0,
            "scene_size": 1000.0,
            "nx": 1024, "ny": 1024,
            "enable_change_detection": True,
        }
    },
]

# ============================================================
# EXECUTION LOOP
# ============================================================

t0_batch = time.time()

for idx, s in enumerate(scenarios):
    s_name = s["name"]
    processor = s["processor"]
    cfg = s["cfg"]
    tdbp = s["tdbp"]
    skip_physics = s.get("skip_physics", False)
    
    # Global defaults
    cfg.setdefault("earth_rotation_mode", "none")
    
    print(f"\n{'='*60}")
    print(f"SCENARIO {idx+1}/{len(scenarios)}: {s_name}")
    print(f"Processor: {processor.upper()}")
    print(f"{'='*60}")
    
    out_dir = os.path.join(OUTPUT_ROOT, s_name)
    os.makedirs(out_dir, exist_ok=True)
    
    cfg["out_dir"] = out_dir
    tdbp["out_dir"] = out_dir
    
    # 1. Write Override Configs
    with open("batch_override.json", "w") as f:
        json.dump(cfg, f, indent=4)
    
    with open("tdbp_override.json", "w") as f:
        json.dump(tdbp, f, indent=4)
    
    # 2. Run Physics (unless skip_physics is set, e.g. for D which already has NPZ)
    if skip_physics:
        # For D: copy the existing NPZ from the output dir to working dir
        npz_src = os.path.join(out_dir, "sar_raw_phase_history.npz")
        if os.path.exists(npz_src):
            shutil.copy2(npz_src, "sar_raw_phase_history.npz")
            print(f"Reusing existing physics data from {npz_src}")
        else:
            print(f"WARNING: skip_physics=True but no NPZ found at {npz_src}!")
            print("Running physics anyway...")
            skip_physics = False
    
    if not skip_physics:
        t0 = time.time()
        res = subprocess.run(["python", "sar_simulation_env.py"])
        if res.returncode != 0:
            print(f"FAILED Physics on {s_name}!")
            continue
        print(f"Physics completed in {time.time()-t0:.0f}s")
    
    # 3. Save config snapshot
    shutil.copy2("batch_override.json", os.path.join(out_dir, "cfg.json"))
    shutil.copy2("tdbp_override.json", os.path.join(out_dir, "tdbp_cfg.json"))
    
    # 4. Run appropriate processor
    t0 = time.time()
    if processor == "spotlight":
        res_proc = subprocess.run(["python", "sar_tdbp_spotlight.py"])
    elif processor == "mbp":
        res_proc = subprocess.run(["python", "sar_tdbp_mbp.py"])
    else:
        print(f"Unknown processor: {processor}")
        continue
    
    if res_proc.returncode != 0:
        print(f"FAILED {processor.upper()} Reconstruction on {s_name}!")
        continue
    
    print(f"Reconstruction completed in {time.time()-t0:.0f}s")
    print(f"SUCCESS: {s_name}")

elapsed = time.time() - t0_batch
print(f"\n{'='*60}")
print(f"ALL {len(scenarios)} SCENARIOS COMPLETE!")
print(f"Total time: {elapsed/3600:.1f} hours")
print(f"Results in: {os.path.abspath(OUTPUT_ROOT)}")
print(f"{'='*60}")
