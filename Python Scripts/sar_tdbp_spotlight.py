import numpy as np
import matplotlib.pyplot as plt
import matplotlib.animation as animation
import torch
import os

C = 299792458.0
device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')

def tdbp_gpu(raw_data, pos_tx, vel_tx, pos_rx, t_start_fast, fs, fc, pulse_width, bandwidth, prf, scene_size=1000.0, nx=1000, ny=1000, scene_center=(0.0, 0.0, 0.0), waveform_type='LFM', tx_baseband=None):
    num_pulses, num_samples = raw_data.shape
    
    x_axis = np.linspace(-scene_size/2, scene_size/2, nx) + scene_center[0]
    y_axis = np.linspace(-scene_size/2, scene_size/2, ny) + scene_center[1]
    
    pos_tx_t = torch.tensor(pos_tx, device=device, dtype=torch.float64)
    # vel_tx_t = torch.tensor(vel_tx, device=device, dtype=torch.float64)
    pos_rx_t = torch.tensor(pos_rx, device=device, dtype=torch.float64)
    
    k_rate = bandwidth / pulse_width
    t_ref = torch.linspace(0, pulse_width, int(pulse_width * fs), device=device, dtype=torch.float64)
    
    if tx_baseband is not None:
        tx_baseband_t = torch.tensor(tx_baseband, device=device, dtype=torch.complex64)
        M_res = len(tx_baseband)
        idx_ref = torch.floor((t_ref / pulse_width) * M_res).long()
        idx_ref = torch.clamp(idx_ref, 0, M_res - 1)
        ref_chirp = tx_baseband_t[idx_ref]
        ref_f = torch.fft.fft(ref_chirp, n=num_samples)
    else: # fallback LFM
        ref_chirp = torch.exp(1j * np.pi * k_rate * (t_ref - pulse_width/2)**2).to(torch.complex64)
        ref_f = torch.fft.fft(ref_chirp, n=num_samples)
    
    # --- Universal Spectral Windowing (Sidelobe Suppression) ---
    # Construct dynamic frequency array aligned to FFT bins
    freqs = torch.fft.fftfreq(num_samples, d=1.0/fs, device=device)
    
    # Normalize frequency relative to the geometric bandwidth [-0.5, 0.5]
    u = freqs / bandwidth
    in_band = torch.abs(u) <= 0.5
    
    if str(waveform_type) in ('NLFM', 'OFDM'):
        # NLFM inherently shapes its spectrum; OFDM subcarriers have equal power by design.
        # Applying a Hamming window would destroy OFDM's orthogonal correlation properties.
        spectral_window = torch.ones_like(u)
    else:
        # Standard Hamming Window Envelope (0.54 + 0.46 * cos)
        spectral_window = 0.54 + 0.46 * torch.cos(2.0 * np.pi * u)
    
    # Zero out pure thermal noise bins lying completely outside the transmitted bandwidth
    spectral_window = torch.where(in_band, spectral_window, torch.zeros_like(spectral_window, device=device))
    
    # Apply to matched filter
    ref_f = ref_f * spectral_window
    
    gx, gy = torch.meshgrid(torch.tensor(x_axis, device=device, dtype=torch.float64), 
                            torch.tensor(y_axis, device=device, dtype=torch.float64), indexing='xy')
    grid_pts = torch.stack((gx.flatten(), gy.flatten(), torch.full_like(gx.flatten(), scene_center[2])), dim=1)
    n_pix = grid_pts.shape[0]
    
    final_img = torch.zeros(n_pix, device=device, dtype=torch.complex64)
    
    pulse_chunk_size = 500
    for p_0 in range(0, num_pulses, pulse_chunk_size):
        p_1 = min(p_0 + pulse_chunk_size, num_pulses)
        
        ptx_c = pos_tx_t[p_0:p_1]
        prx_c = pos_rx_t[p_0:p_1]
        
        rt_chunk = torch.tensor(raw_data[p_0:p_1], device=device, dtype=torch.complex64)
        rf_chunk = torch.fft.fft(rt_chunk, n=num_samples, dim=1)
        rc_chunk = torch.fft.ifft(rf_chunk * torch.conj(ref_f).view(1, -1), dim=1)
        
        sig_chunk = torch.empty((p_1 - p_0, 2, 1, num_samples), device=device, dtype=torch.float32)
        sig_chunk[:, 0, 0, :] = rc_chunk.real
        sig_chunk[:, 1, 0, :] = rc_chunk.imag
        del rt_chunk, rf_chunk, rc_chunk
        
        pixel_batch_size = 16384
        for b_0 in range(0, n_pix, pixel_batch_size):
            b_1 = min(b_0 + pixel_batch_size, n_pix)
            g_batch = grid_pts[b_0:b_1].unsqueeze(0) # [1, B, 3]
            
            diff_tx = g_batch - ptx_c.unsqueeze(1) # [P, B, 3]
            dist_tx = torch.norm(diff_tx, dim=2)   # [P, B]
            
            diff_rx = g_batch - prx_c.unsqueeze(1) # [P, B, 3]
            dist_rx = torch.norm(diff_rx, dim=2)   # [P, B]
            
            tau_final = (dist_tx + dist_rx) / C    # [P, B]
            
            idx_f = (tau_final - t_start_fast) * fs
            idx_norm = 2 * (idx_f / num_samples) - 1
            
            grid = torch.cat((idx_norm.unsqueeze(2), torch.zeros_like(idx_norm).unsqueeze(2)), dim=2).unsqueeze(2)
            sampled = torch.nn.functional.grid_sample(sig_chunk, grid.float(), align_corners=False)
            sampled_c = torch.complex(sampled[:, 0, :, 0], sampled[:, 1, :, 0])
            
            # strictly wrap the output geometry coordinates mapping exclusively inside [-pi, pi] under 64-bit bounds BEFORE mapping directly onto float32 safely
            phi_f64 = torch.fmod(2.0 * np.pi * fc * tau_final, 2.0 * np.pi)
            phase_corr = torch.exp(1j * phi_f64.float())
            
            final_img[b_0:b_1] += torch.sum(sampled_c * phase_corr, dim=0)
            del g_batch, diff_tx, dist_tx, diff_rx, dist_rx, grid, sampled, sampled_c, tau_final, phase_corr, idx_f, idx_norm
            
        del sig_chunk
    
    del ref_f, t_ref
    
    return final_img.reshape(ny, nx).cpu().numpy()

def main():
    import json as _json
    
    # --- Load Override Config ---
    t_cfg = {}
    if os.path.exists("tdbp_override.json"):
        with open("tdbp_override.json") as f:
            t_cfg = _json.load(f)
    
    scene_size = t_cfg.get("scene_size", 1000.0)
    nx = t_cfg.get("nx", 512)
    ny = t_cfg.get("ny", 512)
    out_dir = t_cfg.get("out_dir", ".")
    enable_video = t_cfg.get("enable_video", False)
    enable_cd = t_cfg.get("enable_change_detection", False)
    video_cpi = t_cfg.get("video_cpi", 0.5)
    video_fps = t_cfg.get("video_fps", 5)
    video_duration = t_cfg.get("video_duration", 5.0)
    
    os.makedirs(out_dir, exist_ok=True)
    
    # --- Load Raw Phase History ---
    npz_path = os.path.join(out_dir, "sar_raw_phase_history.npz")
    if not os.path.exists(npz_path):
        # Fallback to current directory for backward compatibility
        npz_path = "sar_raw_phase_history.npz"
    if not os.path.exists(npz_path):
        print(f"Error: sar_raw_phase_history.npz not found in {out_dir} or current directory.")
        return
        
    print(f"Loading SAR raw data from {npz_path}...")
    data = np.load(npz_path, allow_pickle=True)
    
    rx_channels = data['rx_channels']
    pos_tx = data['pos_tx']           
    vel_tx = data['vel_tx']
    pos_rx_all = data['pos_rx']       
    
    raw_sig = rx_channels[0]
    pos_rx = pos_rx_all[0]
    
    t_start_fast = float(data['t_start_fast'])
    fs = float(data['fs'])
    fc = float(data['center_freq'])
    pulse_width = float(data['pulse_width'])
    bandwidth = float(data['bandwidth'])
    prf = float(data['prf'])
    
    scene_center_val = data['scene_center'] if 'scene_center' in data else [0.0, 0.0, 0.0]
    waveform_type = str(data['waveform_type']) if 'waveform_type' in data else 'LFM'
    tx_baseband = data['tx_baseband'] if 'tx_baseband' in data else None
    
    # --- EMI Notch Filter (Pre-Processing) ---
    # Zero out frequency bins corresponding to known interference bands BEFORE backprojection
    # emi_notch_bands: list of [center_freq_hz, bandwidth_hz] (absolute frequencies)
    emi_notch_bands = t_cfg.get("emi_notch_bands", [])
    if len(emi_notch_bands) > 0:
        num_samples = raw_sig.shape[1]
        freqs = np.fft.fftfreq(num_samples, d=1.0/fs)  # baseband frequencies
        
        # Build composite notch mask
        notch_mask = np.ones(num_samples, dtype=np.float64)
        total_notched_bins = 0
        for nb in emi_notch_bands:
            nb_center, nb_bw = nb[0], nb[1]
            # Convert absolute freq to baseband offset
            f_offset = nb_center - fc
            bin_mask = (freqs >= f_offset - nb_bw/2.0) & (freqs <= f_offset + nb_bw/2.0)
            notch_mask[bin_mask] = 0.0
            total_notched_bins += int(np.sum(bin_mask))
        
        print(f"Applying EMI notch filter: {len(emi_notch_bands)} bands, {total_notched_bins} bins zeroed ({100*total_notched_bins/num_samples:.1f}% of spectrum)")
        
        # Make raw_sig writable (np.load returns read-only arrays)
        raw_sig = np.array(raw_sig)
        
        # Apply notch to each pulse in frequency domain
        for i in range(raw_sig.shape[0]):
            spec = np.fft.fft(raw_sig[i])
            spec *= notch_mask
            raw_sig[i] = np.fft.ifft(spec)
    
    range_res = C / (2.0 * bandwidth)
    pixel_m = scene_size / max(nx, ny)
    print(f"Loaded: {raw_sig.shape[0]} pulses | Grid: {nx}x{ny} | Scene: {scene_size}m | Pixel: {pixel_m:.3f}m | Range Res: {range_res:.3f}m | Waveform: {waveform_type}")
    
    ext = [-scene_size/2 + scene_center_val[0], scene_size/2 + scene_center_val[0],
           -scene_size/2 + scene_center_val[1], scene_size/2 + scene_center_val[1]]
    
    # ==============================
    # 1. FULL-CPI STATIC IMAGE
    # ==============================
    cpi_actual = raw_sig.shape[0] / prf
    print(f"Generating fully focused {cpi_actual:.1f}s CPI Image ({nx}x{ny})...")
    img = tdbp_gpu(raw_sig, pos_tx, vel_tx, pos_rx, t_start_fast, fs, fc, pulse_width, bandwidth, prf,
                   scene_size=scene_size, nx=nx, ny=ny,
                   scene_center=scene_center_val, waveform_type=waveform_type, tx_baseband=tx_baseband)
    
    amp_img = np.abs(img)
    g_max = np.max(amp_img)
    if g_max <= 0: g_max = 1.0
    
    # --- LINEAR IMAGE ---
    plt.figure(figsize=(10, 10))
    plt.imshow(amp_img, cmap='gray', vmin=0, vmax=g_max, origin='lower', interpolation='nearest', extent=ext)
    plt.title(f"Spotlight Image Linear ({cpi_actual:.1f}s CPI) - {waveform_type}")
    plt.xlabel("Range (m)")
    plt.ylabel("Azimuth (m)")
    plt.colorbar(label="Amplitude (Linear)")
    fpath = os.path.join(out_dir, "spotlight_image_linear.png")
    plt.savefig(fpath, dpi=400, bbox_inches='tight')
    plt.close()
    print(f"Saved {fpath}")
    
    # --- DB IMAGE ---
    plt.figure(figsize=(10, 10))
    plt.imshow(10 * np.log10(amp_img / g_max + 1e-12), cmap='turbo', vmin=-60, vmax=0, origin='lower', interpolation='nearest', extent=ext)
    plt.title(f"Spotlight Image dB ({cpi_actual:.1f}s CPI) - {waveform_type}")
    plt.xlabel("Range (m)")
    plt.ylabel("Azimuth (m)")
    plt.colorbar(label="Power (dB)")
    fpath = os.path.join(out_dir, "spotlight_image_db.png")
    plt.savefig(fpath, dpi=400, bbox_inches='tight')
    plt.close()
    print(f"Saved {fpath}")
    
    del img, amp_img
    
    # ==============================
    # 2. VideoSAR (optional)
    # ==============================
    if not enable_video:
        print("VideoSAR disabled. Done!")
        return
    
    TOTAL_PULSES = raw_sig.shape[0]
    CPI_PULSES = int(np.ceil(video_cpi * prf))
    STEP_PULSES = int(prf / video_fps)
    NUM_FRAMES = int(video_duration * video_fps)
    
    print(f"Generating VideoSAR: {NUM_FRAMES} frames, {video_fps} FPS, {video_cpi}s CPI per frame")
    
    frames = []
    for f in range(NUM_FRAMES):
        i0 = f * STEP_PULSES
        i1 = i0 + CPI_PULSES
        if i1 > TOTAL_PULSES: break
        
        print(f"  Video Frame {f+1}/{NUM_FRAMES} (pulses {i0}-{i1})")
        img_frame = tdbp_gpu(raw_sig[i0:i1], pos_tx[i0:i1], vel_tx[i0:i1], pos_rx[i0:i1],
                             t_start_fast, fs, fc, pulse_width, bandwidth, prf,
                             scene_size=scene_size, nx=nx, ny=ny,
                             scene_center=scene_center_val, waveform_type=waveform_type, tx_baseband=tx_baseband)
        frames.append(img_frame)
    
    if len(frames) == 0:
        print("No video frames generated!")
        return
    
    abs_frames = [np.abs(fr) for fr in frames]
    v_max = max([np.max(fr) for fr in abs_frames])
    if v_max <= 0: v_max = 1.0
    
    # --- LINEAR VIDEO ---
    fig_lin, ax_lin = plt.subplots(figsize=(8, 8))
    im_lin = ax_lin.imshow(abs_frames[0], cmap='gray', vmin=0, vmax=v_max, origin='lower', interpolation='nearest', extent=ext)
    ax_lin.set_title(f"VideoSAR Linear - {waveform_type}")
    ax_lin.set_xlabel("Range (m)"); ax_lin.set_ylabel("Azimuth (m)")
    fig_lin.colorbar(im_lin, ax=ax_lin, label="Amplitude")
    
    def update_lin(idx):
        im_lin.set_data(abs_frames[idx])
        return [im_lin]
    
    ani_lin = animation.FuncAnimation(fig_lin, update_lin, frames=len(abs_frames), blit=True)
    fpath = os.path.join(out_dir, "spotlight_video_linear.gif")
    ani_lin.save(fpath, writer='pillow', fps=video_fps, dpi=200)
    plt.close(fig_lin)
    print(f"Saved {fpath}")
    
    # --- DB VIDEO ---
    fig_db, ax_db = plt.subplots(figsize=(8, 8))
    im_db = ax_db.imshow(10 * np.log10(abs_frames[0] / v_max + 1e-12), cmap='turbo', vmin=-40, vmax=0, origin='lower', interpolation='nearest', extent=ext)
    ax_db.set_title(f"VideoSAR dB - {waveform_type}")
    ax_db.set_xlabel("Range (m)"); ax_db.set_ylabel("Azimuth (m)")
    fig_db.colorbar(im_db, ax=ax_db, label="Power (dB)")
    
    def update_db(idx):
        im_db.set_data(10 * np.log10(abs_frames[idx] / v_max + 1e-12))
        return [im_db]
    
    ani_db = animation.FuncAnimation(fig_db, update_db, frames=len(abs_frames), blit=True)
    fpath = os.path.join(out_dir, "spotlight_video_db.gif")
    ani_db.save(fpath, writer='pillow', fps=video_fps, dpi=200)
    plt.close(fig_db)
    print(f"Saved {fpath}")
    
    # ==============================
    # 3. Change Detection (optional)
    # ==============================
    if not enable_cd or len(frames) < 2:
        print("Done!")
        return
    
    print("Generating Change Detection Videos...")
    # Coherent change detection: magnitude of complex frame difference
    diff_frames = [np.abs(frames[i+1] - frames[i]) for i in range(len(frames)-1)]
    d_max = max([np.max(df) for df in diff_frames])
    if d_max <= 0: d_max = 1.0
    
    # --- LINEAR CD VIDEO ---
    fig_cd, ax_cd = plt.subplots(figsize=(8, 8))
    im_cd = ax_cd.imshow(diff_frames[0], cmap='hot', vmin=0, vmax=d_max, origin='lower', interpolation='nearest', extent=ext)
    ax_cd.set_title(f"Change Detection Linear - {waveform_type}")
    ax_cd.set_xlabel("Range (m)"); ax_cd.set_ylabel("Azimuth (m)")
    fig_cd.colorbar(im_cd, ax=ax_cd, label="Change Magnitude")
    
    def update_cd_lin(idx):
        im_cd.set_data(diff_frames[idx])
        return [im_cd]
    
    ani_cd = animation.FuncAnimation(fig_cd, update_cd_lin, frames=len(diff_frames), blit=True)
    fpath = os.path.join(out_dir, "change_detection_linear.gif")
    ani_cd.save(fpath, writer='pillow', fps=video_fps, dpi=200)
    plt.close(fig_cd)
    print(f"Saved {fpath}")
    
    # --- DB CD VIDEO ---
    fig_cdb, ax_cdb = plt.subplots(figsize=(8, 8))
    im_cdb = ax_cdb.imshow(10 * np.log10(diff_frames[0] / d_max + 1e-12), cmap='turbo', vmin=-40, vmax=0, origin='lower', interpolation='nearest', extent=ext)
    ax_cdb.set_title(f"Change Detection dB - {waveform_type}")
    ax_cdb.set_xlabel("Range (m)"); ax_cdb.set_ylabel("Azimuth (m)")
    fig_cdb.colorbar(im_cdb, ax=ax_cdb, label="Change (dB)")
    
    def update_cd_db(idx):
        im_cdb.set_data(10 * np.log10(diff_frames[idx] / d_max + 1e-12))
        return [im_cdb]
    
    ani_cdb = animation.FuncAnimation(fig_cdb, update_cd_db, frames=len(diff_frames), blit=True)
    fpath = os.path.join(out_dir, "change_detection_db.gif")
    ani_cdb.save(fpath, writer='pillow', fps=video_fps, dpi=200)
    plt.close(fig_cdb)
    print(f"Saved {fpath}")
    
    print("Done!")

if __name__ == "__main__":
    main()

