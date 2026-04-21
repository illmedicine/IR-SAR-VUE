import numpy as np
import scipy.linalg
from sar_simulation_env import CFG, calculate_trajectories

def construct_hrws():
    print("=== HRWS Multi-Channel DBF Reconstruction ===")
    print("Loading aliased raw phase history arrays...")
    data = np.load("sar_raw_phase_history.npz")
    rx_channels = data['rx_channels']
    N_chan = rx_channels.shape[0]
    
    if N_chan == 1:
        print("Only 1 receiver channel found. No HRWS DBF reconstruction necessary.")
        return
        
    print(f"Applying Krieger DBF Inversion Filter Architecture to {N_chan} aliased channels...")
    N_pulses = rx_channels.shape[1]
    N_samples = rx_channels.shape[2]
    
    prf = float(data['prf'])
    dpca_active = (data.get('dpca_active', False) == True)
    
    # Calculate pos_tx dynamically to avoid needing to re-run the massive simulation
    t_vec = data['slow_time']
    pos_tx, _, _ = calculate_trajectories(N_pulses, t_vec)
    
    # Analyze satellite orbital velocity (v_s) to construct spatial phase delays
    v_s_vec = np.mean(np.diff(pos_tx, axis=0) * prf, axis=0)
    v_s = np.linalg.norm(v_s_vec)
    
    rx_spacing_m = CFG['rx_spacing_m']
    
    # Calculate rigid spatial phase offsets
    if isinstance(rx_spacing_m, str) and rx_spacing_m.lower() == 'dpca':
        spacing_val = (2.0 * v_s) / (N_chan * prf)
        dx = np.array([(k - (N_chan - 1) / 2.0) * spacing_val for k in range(N_chan)])
    elif isinstance(rx_spacing_m, list):
        dx = np.array([float(x) for x in rx_spacing_m])
        if len(dx) < N_chan:
            dx = np.pad(dx, (0, N_chan - len(dx)), 'constant')
    else:
        dx = np.array([(k - (N_chan - 1) / 2.0) * float(rx_spacing_m) for k in range(N_chan)])
        
    print(f"Calculated spatial along-track physical phase center offsets (m): {dx}")
    
    prf_eff = N_chan * prf
    N_big = N_chan * N_pulses
    U_unaliased = np.zeros((N_big, N_samples), dtype=np.complex128)
    
    if dpca_active:
        print("\n*** Auto-DPCA Mode Detected! ***")
        print("Rigid uniform spacing condition satisfied. Bypassing heavy Krieger Matrix Filters.")
        print("Executing pure Time-Domain Interleaving logic (Zippering Phase Centers)...")
        # Interleave exactly: C0[0], C1[0], C2[0]... C0[1], C1[1]...
        phist_reconstructed = np.zeros((N_big, N_samples), dtype=np.complex128)
        for ch in range(N_chan):
            phist_reconstructed[ch::N_chan, :] = rx_channels[ch, :, :]
            
    else:
        # 1. Transform Azimuth fast-time to the Doppler Frequency Domain 
        print("Executing wide Azimuth FFT across all Phase Centers...")
        U_aliased = np.fft.fft(rx_channels, axis=1) # Shape: (N_chan, N_pulses, N_samples)
        
        fa_base = np.fft.fftfreq(N_pulses, 1.0/prf)
        
        # Calculate explicit baseband integer frequency bins
        k_arr = np.round(np.fft.fftfreq(N_pulses, 1.0) * N_pulses).astype(int)
        
        # Determine unfolding shifts (for 4 channels: m = -2, -1, 0, 1)
        m_shift = np.arange(N_chan) - N_chan // 2
        
        print("Running Linear-Algebra Inversion Filter Matrix across entire Doppler spectrum...")
        # 2. Iterate through each baseband Doppler frequency and invert the Transfer Function Matrix
        for i in range(N_pulses):
            f = fa_base[i]
            k = k_arr[i]
            
            # Calculate the N precise frequencies that fold into this aliased baseband bin
            f_m = f + m_shift * prf
            f_m_grid, dx_grid = np.meshgrid(f_m, dx)
            
            # Matrix H: Models the spatial phase shift per channel for each unaliased frequency
            # H[k, m] = exp(-j 2pi * f_m * (dx_k / (2*v_s)))
            H = np.exp(-1j * 2.0 * np.pi * f_m_grid * dx_grid / (2.0 * v_s))
            
            try:
                # Invert the complex transfer matrix mathematically
                P = scipy.linalg.inv(H)
            except scipy.linalg.LinAlgError:
                P = scipy.linalg.pinv(H)
                
            # Extract aliased spatial signals (shape: N_chan, N_samples)
            U_raw = U_aliased[:, i, :]
            
            # Reconstruct exactly un-aliased spectra (unfolded)
            U_true = P @ U_raw
            
            # 3. Insert the perfectly unfolded spectral components into their exact expanded frequency bins
            for m_idx, m_val in enumerate(m_shift):
                K = k + int(m_val) * N_pulses
                idx_big = K % N_big
                U_unaliased[idx_big, :] = U_true[m_idx, :]
                
        print("Executing wide Azimuth IFFT to lock uniform geometry...")
        phist_reconstructed = np.fft.ifft(U_unaliased, axis=0)
    
    # 4. Map back to exact new high-resolution time frames
    cpi_sec = CFG['cpi_sec']
    t_vec_new = np.linspace(-cpi_sec/2, cpi_sec/2, N_big)
    
    # Interpolate orbital trajectory to match the expanded pulse PRF
    pos_tx_new = np.zeros((N_big, 3))
    t_vec_old = data['slow_time']
    for dim in range(3):
        pos_tx_new[:, dim] = np.interp(t_vec_new, t_vec_old, pos_tx[:, dim])
        
    out_file = "sar_raw_phase_history_hrws.npz"
    print(f"Exporting massive mathematically uniform raw phase history array...")
    np.savez(out_file,
             rx_channels=np.expand_dims(phist_reconstructed, axis=0), # CSA assumes index 0 is uniform target
             t_start_fast=data['t_start_fast'],
             fs=data['fs'],
             prf=prf_eff,                # NEW EFFECTIVE HIGH-RES PRF
             pulse_width=data['pulse_width'],
             center_freq=data['center_freq'],
             bandwidth=data['bandwidth'],
             pos_tx=pos_tx_new,          # INTERPOLATED
             slow_time=t_vec_new)        # DENSE SLOW TIME
             
    print(f"\nHRWS DBF Reconstruction Complete! Saved unified data array to {out_file}")
    print(f"Resulting PRF escalated from {prf} Hz to {prf_eff} Hz!")
    print(f"You can natively pass this into the standalone CSA Processor now via `python sar_csa_processing.py` replacing the base `.npz` file argument.")

if __name__ == '__main__':
    construct_hrws()
