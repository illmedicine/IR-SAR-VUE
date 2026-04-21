import os
import sys
import json
import numpy as np
import subprocess
import shutil

# --- Constants ---
C = 299792458.0
Re = 6371000.0
GM = 3.986004418e14

def sar_focus_csa(phist, center_wavelength_m, pulse_width_sec, chirp_rate_hzpsec, sample_rate_hz, prf_hz, platform_speed_mps, range_ref_m, t_start_fast):
    """
    Implements Chirp Scaling Algorithm using CPU.
    phist: Raw phase history (N_pulses x N_samples)
    """
    import scipy.fft as fft
    import gc
    
    # Cast to complex64 to save memory
    phist = phist.astype(np.complex64)
    
    # 0. Setup Axes
    N_az, N_rg = phist.shape
    lam = center_wavelength_m
    Kr = chirp_rate_hzpsec
    Vr = platform_speed_mps
    c = C
    
    dt_fast = 1.0 / sample_rate_hz
    tau = t_start_fast + np.arange(N_rg) * dt_fast
    fr = fft.fftfreq(N_rg, dt_fast)
    fa = fft.fftfreq(N_az, 1.0/prf_hz)
    R_ref = range_ref_m
    
    # --- Step 1: Azimuth FFT -> Range-Doppler Domain ---
    print("      [CSA] Step 1: Azimuth FFT and Chirp Scaling...", flush=True)
    # Apply in-place spatial phase multipliers instead of memory-copying fftshift
    shift_0 = N_az // 2
    phase_0 = np.exp(1j * 2.0 * np.pi * shift_0 * np.arange(N_az) / N_az)[:, None].astype(np.complex64)
    phist *= phase_0
    S_rd = fft.fft(phist, axis=0, overwrite_x=True) 
    fa = fft.fftshift(fa)
    
    arg_sqrt = 1.0 - (lam * fa / (2.0 * Vr))**2
    arg_sqrt[arg_sqrt < 0] = 1e-9
    D_fa = np.sqrt(arg_sqrt)
    Cs_fa = (1.0 / D_fa) - 1.0
    
    tau_ref_fa = 2.0 * R_ref / (c * D_fa)
    
    print(f"      [CSA] System memory optimization: chunking ({N_az}x{N_rg}) matrix over axis 0...", flush=True)
    chunk_size = 500
    for i in range(0, N_az, chunk_size):
        end = min(i + chunk_size, N_az)
        yy = Cs_fa[i:end, np.newaxis]
        t_ref = tau_ref_fa[i:end, np.newaxis]
        xx = tau[np.newaxis, :]
        phi_1 = np.exp(-1j * np.pi * Kr * yy * (xx - t_ref)**2).astype(np.complex64)
        S_rd[i:end, :] *= phi_1
        
    gc.collect()
    
    # --- Step 2: Range FFT -> 2D Frequency Domain ---
    print("      [CSA] Step 2: Range FFT, Range Compression, & Bulk RCMC...", flush=True)
    shift_1 = N_rg // 2
    phase_1 = np.exp(1j * 2.0 * np.pi * shift_1 * np.arange(N_rg) / N_rg)[None, :].astype(np.complex64)
    S_rd *= phase_1
    S_2df = fft.fft(S_rd, axis=1, overwrite_x=True)
    fr = fft.fftshift(fr)
    
    for i in range(0, N_az, chunk_size):
        end = min(i + chunk_size, N_az)
        cs_fa_chunk = Cs_fa[i:end, np.newaxis]
        fr_chunk = fr[np.newaxis, :]
        
        phi_2_rc = np.pi * (fr_chunk**2) / (Kr * (1.0 + cs_fa_chunk))
        phi_2_rcmc = 4.0 * np.pi * R_ref * cs_fa_chunk * fr_chunk / c
        phi_2 = np.exp(1j * (phi_2_rc + phi_2_rcmc)).astype(np.complex64)
        S_2df[i:end, :] *= phi_2
        
    gc.collect()
    
    # --- Step 3: Range IFFT -> Range-Doppler Domain ---
    print("      [CSA] Step 3: Range IFFT & Azimuth Compression...", flush=True)
    # Replaces fft.ifftshift(axis=1) before ifft using inverted spatial shifts
    S_rd_2 = fft.ifft(S_2df, axis=1, overwrite_x=True)
    ishift_1 = (N_rg + 1) // 2
    iphase_1 = np.exp(1j * 2.0 * np.pi * ishift_1 * np.arange(N_rg) / N_rg)[None, :].astype(np.complex64)
    S_rd_2 *= iphase_1
    
    R_vec = c * tau / 2.0
    tau_diff = tau[np.newaxis, :] - (2.0 * R_ref / c)
    
    for i in range(0, N_az, chunk_size):
        end = min(i + chunk_size, N_az)
        d_fa_chunk = D_fa[i:end, np.newaxis]
        cs_fa_chunk = Cs_fa[i:end, np.newaxis]
        r_grid_chunk = R_vec[np.newaxis, :]
        
        phi_3_ac = 4.0 * np.pi * r_grid_chunk * d_fa_chunk / lam
        phi_3_resid = -np.pi * Kr * cs_fa_chunk * (1.0 + cs_fa_chunk) * (tau_diff**2)
        
        phi_3 = np.exp(1j * (phi_3_ac + phi_3_resid)).astype(np.complex64)
        S_rd_2[i:end, :] *= phi_3
        
    gc.collect()
    
    # --- Step 4: Azimuth IFFT -> Image Domain ---
    print("      [CSA] Step 4: Azimuth IFFT (Image Domain Formation)...", flush=True)
    img = fft.ifft(S_rd_2, axis=0, overwrite_x=True)
    ishift_0 = (N_az + 1) // 2
    iphase_0 = np.exp(1j * 2.0 * np.pi * ishift_0 * np.arange(N_az) / N_az)[:, None].astype(np.complex64)
    img *= iphase_0
    
    range_axis = R_vec
    t_slow = np.arange(N_az) / prf_hz
    t_slow -= np.mean(t_slow)
    cross_range_axis = t_slow * Vr
    
    return img.T, range_axis, cross_range_axis

def main():
    scenario_name = "default_stap_scenario"
    process_only = False
    
    if "--process-only" in sys.argv:
        process_only = True
        sys.argv.remove("--process-only")
        
    if len(sys.argv) > 1:
        scenario_name = sys.argv[1]
        
    print(f"=== Running STAP Pipeline: {scenario_name} ===")
    
    # Manage Subfolders
    base_dir = "STAP Results"
    scenario_dir = os.path.join(base_dir, scenario_name)
    os.makedirs(scenario_dir, exist_ok=True)
    
    # Write Overrides
    override_config = {
        'center_freq_hz': 2.0e9,
        'tx_power_w': 20000.0,
        'altitude_m': 350e3,
        'duty_cycle_pct': 20.0,
        'prf_hz': 8000.0,
        'sar_mode': 'stripmap',
        'grazing_angle_deg': 50.0,
        'num_clutter_pts': 10000,
        'num_cars': 10,
        'num_jets': 3,
        'jet_alt_m': 1000.0,
        'waveform_type': 'LFM',
        'earth_rotation_mode': 'compensated',
        'scene_lat_deg': 45.0,
        'num_rx_antennas': 2,
        'rx_spacing_m': 'dpca',
        'is_bistatic': True,
        'out_dir': scenario_dir
    }
    
    if "--wide" in sys.argv:
        override_config['area_size_m'] = (15000, 15000)
        override_config['antenna_gain_az_dbi'] = 16.0
        override_config['antenna_gain_el_dbi'] = 18.0
        sys.argv.remove("--wide")
    else:
        override_config['area_size_m'] = (3000, 3000)
        override_config['antenna_gain_az_dbi'] = 23.0
        override_config['antenna_gain_el_dbi'] = 23.0
        
    # Dynamically Compute Geometric CPI Requirement
    R_sat = Re + override_config['altitude_m']
    V_sat = np.sqrt(GM / R_sat)
    theta_look_rad = np.radians(90.0 - override_config['grazing_angle_deg'])
    R_scene = Re
    theta_inc_rad = np.arcsin((R_sat / R_scene) * np.sin(theta_look_rad))
    gamma_rad = theta_inc_rad - theta_look_rad
    R0 = np.sqrt(R_scene**2 + R_sat**2 - 2 * R_scene * R_sat * np.cos(gamma_rad))
    
    G_az_lin = 10**(override_config.get('antenna_gain_az_dbi', 23.0) / 10.0)
    az_beamwidth_rad = 1.772 / G_az_lin
    footprint_az_m = R0 * az_beamwidth_rad
    
    total_az_m = footprint_az_m + override_config['area_size_m'][1]
    override_config['cpi_sec'] = (total_az_m / V_sat) * 1.05  # 5% buffer padding
    print(f"Dynamically calculated CPI for target swath: {override_config['cpi_sec']:.2f} seconds")

    with open("batch_override.json", "w") as f:
        json.dump(override_config, f, indent=4)
        
    if not process_only:
        # Execute Environment Sim
        print("\n[1/3] Executing Modular SAR Environment Engine...")
        result = subprocess.run(["python", "sar_simulation_env.py"])
        if result.returncode != 0:
            print("Simulation failed. Exiting STAP Pipeline.")
            return
    else:
        print("\n[1/3] Skipping Simulation (--process-only passed). Using existing data...")
        
    # Process Outputs
    print("\n[2/3] Loading Raw Multi-Channel Phase History for CSA...")
    raw_file = os.path.join(scenario_dir, "sar_raw_phase_history.npz")
    data = np.load(raw_file)
    rx_channels = data['rx_channels']
    t_start_fast = float(data['t_start_fast'])
    fs = float(data['fs'])
    prf = float(data['prf'])
    pulse_width = float(data['pulse_width'])
    center_freq = float(data['center_freq'])
    bandwidth = float(data['bandwidth'])
    
    Lambda = C / center_freq
    R_sat = Re + override_config['altitude_m']
    V_sat = np.sqrt(GM / R_sat)
    V_eff = V_sat * np.sqrt(Re / R_sat)
    
    # Re-derive R0 reference range
    theta_look_rad = np.radians(90.0 - override_config['grazing_angle_deg'])
    R_scene = Re + 0.0
    theta_inc_rad = np.arcsin((R_sat / R_scene) * np.sin(theta_look_rad))
    gamma_rad = theta_inc_rad - theta_look_rad
    R0 = np.sqrt(R_scene**2 + R_sat**2 - 2 * R_scene * R_sat * np.cos(gamma_rad))
    
    # DPCA Shift
    print("  Applying DPCA Temporal Alignment...")
    raw_rx1_shift = rx_channels[0][1:, :]
    raw_rx2_shift = rx_channels[1][:-1, :]
    
    print("\n[3/3] Focusing Co-registered Channels via CSA...")
    chirp_rate = bandwidth / pulse_width
    slc1, rax, cax = sar_focus_csa(raw_rx1_shift, Lambda, pulse_width, chirp_rate, fs, prf, V_eff, R0, t_start_fast)
    slc2, _, _     = sar_focus_csa(raw_rx2_shift, Lambda, pulse_width, chirp_rate, fs, prf, V_eff, R0, t_start_fast)
    
    print("  Saving focused results...")
    focused_file = os.path.join(scenario_dir, "stap_focused_results.npz")
    
    grax = (rax - R0) / np.sin(theta_inc_rad)
    
    np.savez(focused_file, 
             slc1=slc1, 
             slc2=slc2, 
             range_axis=grax, 
             cross_range=cax)
    
    print(f"\nPipeline Complete! Results saved to '{scenario_dir}'.")
    print(f"Run 'python stap_viewer.py {scenario_name}' to launch viewer.")
    
if __name__ == "__main__":
    main()
