import numpy as np
import os
import matplotlib.pyplot as plt

def run_csa_pipeline(raw_file="sar_raw_phase_history.npz", output_file="sar_csa_stages.npz"):
    print(f"Loading raw phase history from {raw_file}...")
    
    if not os.path.exists(raw_file):
        print(f"Error: {raw_file} not found. Run sar_simulation_env.py first.")
        return
        
    data = np.load(raw_file)
    
    # 1. Load Parameters
    # Convert scalar arrays back to floats
    t_start_fast = float(data['t_start_fast'])
    fs = float(data['fs'])
    prf = float(data['prf'])
    pulse_width = float(data['pulse_width'])
    center_freq = float(data['center_freq'])
    bandwidth = float(data['bandwidth'])
    
    slow_time = data['slow_time']
    # Use Channel 0 (the first/main receiver) for single-channel CSA
    phist = data['rx_channels'][0] 
    
    print(f"Data Loaded: {phist.shape[0]} pulses, {phist.shape[1]} samples.")
    print(f"PRF: {prf} Hz, Bandwidth: {bandwidth/1e6} MHz")
    
    # --- Physical Constants & Geometry Derivation ---
    c = 299792458.0
    lam = c / center_freq
    Kr = bandwidth / pulse_width
    
    # We must approximate orbital velocity and reference range from standard defaults
    # (In a real system these come from orbit ephemeris, but we can back-calculate them)
    Re = 6371000.0
    h_approx = 500e3
    R_sat = Re + h_approx
    GM = 3.986004418e14
    V_sat = np.sqrt(GM / R_sat)
    
    # Effective Velocity for airborne-equivalent SAR math
    Vr = V_sat * np.sqrt(Re / R_sat) 
    
    # Mid-swath reference range R_ref calculation (assuming 40 deg grazing)
    theta_look_rad = np.radians(50.0) # 90 - 40
    theta_inc_rad = np.arcsin((R_sat / Re) * np.sin(theta_look_rad))
    gamma_rad = theta_inc_rad - theta_look_rad
    R_ref = np.sqrt(Re**2 + R_sat**2 - 2 * Re * R_sat * np.cos(gamma_rad))
    
    print(f"Calculated Vr: {Vr:.2f} m/s, R_ref: {R_ref:.2f} meters")

    # =========================================================================
    # CHIRP SCALING ALGORITHM (CSA)
    # =========================================================================
    import numpy.fft as fft
    
    stages = {}
    
    # Define axes
    N_az, N_rg = phist.shape
    
    # Fast Time (Range)
    dt_fast = 1.0 / fs
    tau = t_start_fast + np.arange(N_rg) * dt_fast
    
    # Range Frequency
    fr = fft.fftfreq(N_rg, dt_fast)
    
    # Azimuth Frequency
    fa = fft.fftfreq(N_az, 1.0/prf)
    
    # --- Checkpoint 1: Raw Baseband Time Domain ---
    stages['01_raw_time'] = np.copy(phist)
    
    print("Step 1: Azimuth FFT -> Range-Doppler Domain")
    # S(tau, fa)
    S_rd = fft.fft(phist, axis=0)
    S_rd = fft.fftshift(S_rd, axes=0)
    fa = fft.fftshift(fa)
    
    # --- Checkpoint 2: Range-Doppler Domain ---
    stages['02_range_doppler'] = np.copy(S_rd)
    
    print("Step 2: Chirp Scaling Phase Multiply")
    # Calculate Range Migration Factor D(fa)
    arg_sqrt = 1.0 - (lam * fa / (2.0 * Vr))**2
    arg_sqrt[arg_sqrt < 0] = 1e-9 # Prevent invalid roots
    D_fa = np.sqrt(arg_sqrt)
    
    # Chirp Scaling Factor Cs(fa)
    Cs_fa = (1.0 / D_fa) - 1.0
    
    # Reference Delay
    tau_ref_fa = 2.0 * R_ref / (c * D_fa)
    
    # Grids
    XX, YY = np.meshgrid(tau, Cs_fa) 
    _, TauRef = np.meshgrid(tau, tau_ref_fa)
    
    # Chirp Scaling Phase Phi_1
    Phi_1 = np.exp(-1j * np.pi * Kr * YY * (XX - TauRef)**2)
    S_sc = S_rd * Phi_1
    
    # --- Checkpoint 3: Scaled Range-Doppler Domain ---
    stages['03_cs_applied_rd'] = np.copy(S_sc)
    
    print("Step 3: Range FFT -> 2D Frequency Domain")
    S_2df = fft.fft(S_sc, axis=1)
    S_2df = fft.fftshift(S_2df, axes=1)
    fr = fft.fftshift(fr)
    
    print("Step 4: Range Compression and RCMC Multiply")
    FR, _ = np.meshgrid(fr, fa) 
    _, CS_FA = np.meshgrid(fr, Cs_fa)
    
    # Range Compression Phase (Cancel the chirp)
    phi_2_rc = np.pi * (FR**2) / (Kr * (1.0 + CS_FA))
    
    # Bulk RCMC Phase (Shift reference range to correct trajectory)
    phi_2_rcmc = 4.0 * np.pi * R_ref * CS_FA * FR / c
    
    Phi_2 = np.exp(1j * (phi_2_rc + phi_2_rcmc))
    S_rc = S_2df * Phi_2
    
    # --- Checkpoint 4: 2D Frequency Domain (Post PC/RCMC) ---
    stages['04_rc_rcmc_2df'] = np.copy(S_rc)
    
    print("Step 5: Range IFFT -> Straightened Range-Doppler Domain")
    S_rd_2 = fft.ifft(fft.ifftshift(S_rc, axes=1), axis=1)
    
    # --- Checkpoint 5: Range-Doppler Domain (Straightened Chirps) ---
    stages['05_rc_rcmc_rd'] = np.copy(S_rd_2)
    
    print("Step 6: Azimuth Compression Phase Multiply")
    # Grid for R mapping
    R_vec = c * tau / 2.0
    R_grid, _ = np.meshgrid(R_vec, fa) 
    _, D_FA_2 = np.meshgrid(R_vec, D_fa)
    
    # Azimuth Compression Phase filter
    phi_3_ac = 4.0 * np.pi * R_grid * D_FA_2 / lam
    
    # Residual Phase Correction
    tau_diff = XX - (2.0 * R_ref / c)
    phi_3_resid = -np.pi * Kr * Cs_fa[:, np.newaxis] * (1.0 + Cs_fa[:, np.newaxis]) * (tau_diff**2)
    
    Phi_3 = np.exp(1j * (phi_3_ac + phi_3_resid))
    S_focused_rd = S_rd_2 * Phi_3
    
    # --- Checkpoint 6: Range-Doppler Domain (Post Azimuth Comp) ---
    stages['06_ac_applied_rd'] = np.copy(S_focused_rd)
    
    print("Step 7: Azimuth IFFT -> Final Image Domain")
    img = fft.ifft(fft.ifftshift(S_focused_rd, axes=0), axis=0)
    
    # Coordinates
    t_slow_zero_mean = slow_time - np.mean(slow_time)
    cross_range_axis = t_slow_zero_mean * Vr
    
    # --- Checkpoint 7: Focused Image ---
    stages['07_focused_image'] = np.copy(img)
    
    print(f"Saving checkpoints to {output_file}...")
    np.savez(output_file, 
             range_axis=R_vec, 
             cross_range_axis=cross_range_axis,
             **stages)
             
    print("SAR CSA Processing Complete.")

if __name__ == "__main__":
    run_csa_pipeline()
