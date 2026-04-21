import numpy as np
import torch
import os
import shutil
import json
import matplotlib.pyplot as plt
import matplotlib.animation as animation
from tqdm import tqdm

C = 299792458.0
device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')

def tdbp_mbp_gpu(raw_sig, pos_tx, vel_tx, pos_rx, t_start_fast, fs, fc, pulse_width, bandwidth, prf, scene_size=1000.0, nx=512, ny=512, scene_center=(0.0, 0.0, 0.0), waveform_type='LFM', tx_baseband=None, vel_focus=[0.0, 0.0, 0.0], t_pulses=None, z_focus=0.0):
    num_pulses, num_samples = raw_sig.shape
    
    x_axis = np.linspace(-scene_size/2, scene_size/2, nx) + scene_center[0]
    y_axis = np.linspace(-scene_size/2, scene_size/2, ny) + scene_center[1]
    
    pos_tx_t = torch.tensor(pos_tx, device=device, dtype=torch.float64)
    vel_tx_t = torch.tensor(vel_tx, device=device, dtype=torch.float64)
    
    k_rate = bandwidth / pulse_width
    
    # 1. GENERATE REFERENCE CHIRP / SPECTRAL WINDOWING (Arbitrary Waveform Support)
    if tx_baseband is not None:
        tx_baseband_t = torch.tensor(tx_baseband, device=device, dtype=torch.complex64)
        M_res = len(tx_baseband)
        t_ref_norm = torch.linspace(0, pulse_width, int(pulse_width * fs), device=device, dtype=torch.float64)
        idx_ref = torch.floor((t_ref_norm / pulse_width) * M_res).long()
        idx_ref = torch.clamp(idx_ref, 0, M_res - 1)
        ref_chirp = tx_baseband_t[idx_ref]
        ref_f = torch.fft.fft(ref_chirp, n=num_samples)
    else: 
        t_ref = torch.linspace(0, pulse_width, int(pulse_width * fs), device=device, dtype=torch.float64)
        ref_chirp = torch.exp(1j * np.pi * k_rate * (t_ref - pulse_width/2)**2).to(torch.complex64)
        ref_f = torch.fft.fft(ref_chirp, n=num_samples)
    
    # Spectral Windowing mapped accurately
    freqs = torch.fft.fftfreq(num_samples, d=1.0/fs, device=device)
    u = freqs / bandwidth
    in_band = torch.abs(u) <= 0.5
    if str(waveform_type) in ('NLFM', 'OFDM'):
        spectral_window = torch.ones_like(u)
    else:
        spectral_window = 0.54 + 0.46 * torch.cos(2.0 * np.pi * u)
    spectral_window = torch.where(in_band, spectral_window, torch.zeros_like(spectral_window, device=device))
    ref_f = ref_f * spectral_window
    
    gx, gy = torch.meshgrid(torch.tensor(x_axis, device=device, dtype=torch.float64), 
                            torch.tensor(y_axis, device=device, dtype=torch.float64), indexing='xy')
    grid_pts = torch.stack((gx.flatten(), gy.flatten(), torch.full_like(gx.flatten(), z_focus)), dim=1)
    n_pix = grid_pts.shape[0]
    
    final_img = torch.zeros(n_pix, device=device, dtype=torch.complex64)
    v_f = torch.tensor(vel_focus, device=device, dtype=torch.float64).view(1, 1, 3)
    t_c = torch.mean(torch.tensor(t_pulses, device=device, dtype=torch.float64))
    
    pulse_chunk_size = 500
    for p_0 in range(0, num_pulses, pulse_chunk_size):
        p_1 = min(p_0 + pulse_chunk_size, num_pulses)
        
        rt_chunk = torch.tensor(raw_sig[p_0:p_1], device=device, dtype=torch.complex64)
        rf_chunk = torch.fft.fft(rt_chunk, n=num_samples, dim=1)
        rc_chunk = torch.fft.ifft(rf_chunk * torch.conj(ref_f).view(1, -1), dim=1)
        
        sig_chunk = torch.empty((p_1 - p_0, 2, 1, num_samples), device=device, dtype=torch.float32)
        sig_chunk[:, 0, 0, :] = rc_chunk.real
        sig_chunk[:, 1, 0, :] = rc_chunk.imag
        del rt_chunk, rf_chunk, rc_chunk
        
        ptx_c = pos_tx_t[p_0:p_1]
        vtx_c = vel_tx_t[p_0:p_1]
        t_p_c = torch.tensor(t_pulses[p_0:p_1], device=device, dtype=torch.float64).view(-1, 1, 1)
        dt = t_p_c - t_c
        
        batch_size = 8192
        for b_0 in range(0, n_pix, batch_size):
            b_1 = min(b_0 + batch_size, n_pix)
            g_batch = grid_pts[b_0:b_1].unsqueeze(0)
            
            g_batch_expanded = g_batch + v_f * dt
            diff_tx = g_batch_expanded - ptx_c.unsqueeze(1)
            dist_tx = torch.norm(diff_tx, dim=2)
            
            r_unit = diff_tx / dist_tx.unsqueeze(2)
            v_rel = vtx_c.unsqueeze(1) - v_f 
            v_rad = torch.sum(v_rel * r_unit, dim=2)
            t_shift = (-fc * (2 * v_rad / C)) / k_rate  
            
            tau_approx = 2 * dist_tx / C 
            pos_rx_c = ptx_c.unsqueeze(1) + vtx_c.unsqueeze(1) * tau_approx.unsqueeze(2)
            g_rx = g_batch_expanded + v_f * tau_approx.unsqueeze(2)
            dist_rx = torch.norm(g_rx - pos_rx_c, dim=2)
            tau_final = (dist_tx + dist_rx) / C
            
            idx_f = (tau_final - t_start_fast + t_shift) * fs
            idx_norm = 2 * (idx_f / num_samples) - 1
            
            grid = torch.cat((idx_norm.unsqueeze(2), torch.zeros_like(idx_norm).unsqueeze(2)), dim=2).unsqueeze(2)
            sampled = torch.nn.functional.grid_sample(sig_chunk, grid.float(), align_corners=False)
            sampled_c = torch.complex(sampled[:, 0, :, 0], sampled[:, 1, :, 0])
            
            phi_f64 = torch.fmod(2.0 * np.pi * fc * tau_final, 2.0 * np.pi)
            phase_corr = torch.exp(1j * phi_f64.float())
            
            final_img[b_0:b_1] += torch.sum(sampled_c * phase_corr, dim=0)
            
        del sig_chunk
        
    return final_img.reshape(ny, nx).cpu().numpy()

if __name__ == "__main__":
    # 1. LOAD CONFIGURATIONS OVERRIDE DYNAMICALLY
    tgt_vel = [0.0, 0.0, 0.0]
    z_focus_val = 0.0
    if os.path.exists("tdbp_override.json"):
        with open("tdbp_override.json", "r") as f:
            t_cfg = json.load(f)
            tgt_vel = t_cfg.get("v_tgt", [0.0, 0.0, 0.0])
            z_focus_val = t_cfg.get("z_focus", 0.0)
            scene_size_val = t_cfg.get("scene_size", 1000.0)
            nx_val = t_cfg.get("nx", 512)
            ny_val = t_cfg.get("ny", 512)
            out_dir = t_cfg.get("out_dir", "./batch_output")
            enable_cd = t_cfg.get("enable_change_detection", False)
            center_mode = t_cfg.get("center_mode", "midpoint")  # 'midpoint' or 'track'
    else:
        out_dir = "./batch_output"
        scene_size_val = 1000.0
        nx_val = 512
        ny_val = 512
        enable_cd = False
        center_mode = "midpoint"
        
    if not os.path.exists(out_dir):
        os.makedirs(out_dir)

    print("Loading SAR raw mBP data from targeted directory...")
    data = np.load(os.path.join(out_dir, "sar_raw_phase_history.npz"))
    
    raw_sig_all = data['rx_channels']
    raw_sig = raw_sig_all[0]
    pos_tx_all = data['pos_tx']
    vel_tx_all = data['vel_tx']
    pos_rx_all = data['pos_rx'][0]  # First channel 
    
    t_start_fast = float(data['t_start_fast'])
    fs = float(data['fs'])
    fc = float(data['center_freq'])
    pulse_width = float(data['pulse_width'])
    bandwidth = float(data['bandwidth'])
    prf = float(data['prf'])
    
    scene_center_val = data['scene_center'] if 'scene_center' in data else [0.0, 0.0, 0.0]
    waveform_type = str(data['waveform_type']) if 'waveform_type' in data else 'LFM'
    tx_baseband = data['tx_baseband'] if 'tx_baseband' in data else None
    t_vec = data['slow_time']
    num_pulses = raw_sig.shape[0]
    
    print(f"Tracking mBP velocity: {tgt_vel} m/s | Center mode: {center_mode}")
    
    # Store the original scene center for per-frame centering
    scene_center_base = [float(scene_center_val[0]), float(scene_center_val[1]), z_focus_val]
    
    if center_mode == 'midpoint' and tgt_vel != [0.0, 0.0, 0.0]:
        # Center scene on trajectory midpoint so target visibly flies THROUGH the frame
        t_mid = float((t_vec[0] + t_vec[-1]) / 2.0)
        scene_center_val = [scene_center_base[0] + tgt_vel[0] * t_mid,
                            scene_center_base[1] + tgt_vel[1] * t_mid,
                            z_focus_val]
        print(f"Scene centered on trajectory midpoint at t={t_mid:.1f}s: {scene_center_val}")
    
    # --- VIDEOSAR SLIDING ALGORITHM ---
    cpi_sec = float(t_cfg.get('video_cpi', 1.0))
    cpi_pulses = int(np.round(cpi_sec * prf))
    
    fps = int(t_cfg.get('video_fps', 5))
    num_frames = int( (t_vec[-1] - t_vec[0] - cpi_sec) * fps )
    if num_frames < 1: num_frames = 1
    
    step_pulses = int(prf / fps)
    
    print(f"Generating {num_frames} frames tracking exclusively at {fps} FPS natively!")
    
    frames = []
    for f_idx in tqdm(range(num_frames)):
        i0 = f_idx * step_pulses
        i1 = i0 + cpi_pulses
        if i1 > num_pulses:
            break
            
        c_sig = raw_sig[i0:i1]
        c_ptx = pos_tx_all[i0:i1]
        c_vtx = vel_tx_all[i0:i1]
        c_prx = pos_rx_all[i0:i1]
        c_t = t_vec[i0:i1]
        
        # For 'track' mode: re-center scene on target at each CPI's center time
        if center_mode == 'track' and tgt_vel != [0.0, 0.0, 0.0]:
            t_cpi_center = float((c_t[0] + c_t[-1]) / 2.0)
            frame_center = [scene_center_base[0] + tgt_vel[0] * t_cpi_center,
                            scene_center_base[1] + tgt_vel[1] * t_cpi_center,
                            z_focus_val]
        else:
            frame_center = scene_center_val
        
        img_frame = tdbp_mbp_gpu(c_sig, c_ptx, c_vtx, c_prx, t_start_fast, fs, fc, pulse_width, bandwidth, prf, 
                                 scene_size=scene_size_val, nx=nx_val, ny=ny_val,
                                 scene_center=frame_center, waveform_type=waveform_type, tx_baseband=tx_baseband, 
                                 vel_focus=tgt_vel, t_pulses=c_t, z_focus=z_focus_val)
        frames.append(img_frame)
        
    if len(frames) > 0:
        abs_frames = [np.abs(fr) for fr in frames]
        g_max = max([np.max(fr) for fr in abs_frames])
        g_max = g_max if g_max > 0 else 1.0
        
        ext = [-scene_size_val/2, scene_size_val/2, -scene_size_val/2, scene_size_val/2] 
        t_base = "Spotlight SAR" if tgt_vel == [0.0, 0.0, 0.0] else f"mBP Target Tracker (V: {tgt_vel})"
        
        # --- DB VIDEO ---
        fig_db, ax_db = plt.subplots(figsize=(8, 8))
        im_db = ax_db.imshow(10 * np.log10(abs_frames[0] / g_max + 1e-12), cmap='turbo', vmin=-40, vmax=0, origin='lower', extent=ext)
        ax_db.set_title(f"{t_base} dB")
        ax_db.set_xlabel("Range (m)")
        ax_db.set_ylabel("Azimuth (m)")
        plt.colorbar(im_db, ax=ax_db, label="Power (dB)")
        
        def update_db(idx):
            im_db.set_data(10 * np.log10(abs_frames[idx] / g_max + 1e-12))
            return [im_db]
        
        ani_db = animation.FuncAnimation(fig_db, update_db, frames=len(abs_frames), blit=True)
        ani_db.save(os.path.join(out_dir, "spotlight_video_db.gif"), writer='pillow', fps=fps, dpi=400)
        plt.close(fig_db)

        # --- LINEAR VIDEO ---
        fig_lin, ax_lin = plt.subplots(figsize=(8, 8))
        im_lin = ax_lin.imshow(abs_frames[0], cmap='gray', vmin=0, vmax=g_max, origin='lower', extent=ext)
        ax_lin.set_title(f"{t_base} Linear")
        ax_lin.set_xlabel("Range (m)")
        ax_lin.set_ylabel("Azimuth (m)")
        plt.colorbar(im_lin, ax=ax_lin, label="Amplitude (Linear)")
        
        def update_lin(idx):
            im_lin.set_data(abs_frames[idx])
            return [im_lin]
        
        ani_lin = animation.FuncAnimation(fig_lin, update_lin, frames=len(abs_frames), blit=True)
        ani_lin.save(os.path.join(out_dir, "spotlight_video_linear.gif"), writer='pillow', fps=fps, dpi=400)
        plt.close(fig_lin)
        
        # --- DB IMAGE ---
        plt.figure(figsize=(8,8))
        plt.imshow(10 * np.log10(abs_frames[-1] / g_max + 1e-12), cmap='turbo', vmin=-40, vmax=0, origin='lower', extent=ext)
        plt.title(f"Final CPI Image dB")
        plt.xlabel("Range (m)")
        plt.ylabel("Azimuth (m)")
        plt.colorbar(label="Power (dB)")
        plt.savefig(os.path.join(out_dir, "spotlight_image_db.png"), dpi=400)
        plt.close()

        # --- LINEAR IMAGE ---
        plt.figure(figsize=(8,8))
        plt.imshow(abs_frames[-1], cmap='gray', vmin=0, vmax=g_max, origin='lower', extent=ext)
        plt.title(f"Final CPI Image Linear")
        plt.xlabel("Range (m)")
        plt.ylabel("Azimuth (m)")
        plt.colorbar(label="Amplitude (Linear)")
        plt.savefig(os.path.join(out_dir, "spotlight_image_linear.png"), dpi=400)
        plt.close()
        
        # ==============================
        # CHANGE DETECTION (optional)
        # ==============================
        if enable_cd and len(frames) >= 2:
            print("Generating mBP Change Detection Videos...")
            diff_frames = [np.abs(frames[i+1] - frames[i]) for i in range(len(frames)-1)]
            d_max = max([np.max(df) for df in diff_frames])
            if d_max <= 0: d_max = 1.0
            
            # --- LINEAR CD VIDEO ---
            fig_cd, ax_cd = plt.subplots(figsize=(8, 8))
            im_cd = ax_cd.imshow(diff_frames[0], cmap='hot', vmin=0, vmax=d_max, origin='lower', extent=ext)
            ax_cd.set_title(f"{t_base} Change Detection Linear")
            ax_cd.set_xlabel("Range (m)")
            ax_cd.set_ylabel("Azimuth (m)")
            plt.colorbar(im_cd, ax=ax_cd, label="Change Magnitude")
            
            def update_cd_lin(idx):
                im_cd.set_data(diff_frames[idx])
                return [im_cd]
            
            ani_cd = animation.FuncAnimation(fig_cd, update_cd_lin, frames=len(diff_frames), blit=True)
            ani_cd.save(os.path.join(out_dir, "change_detection_linear.gif"), writer='pillow', fps=fps, dpi=400)
            plt.close(fig_cd)
            
            # --- DB CD VIDEO ---
            fig_cdb, ax_cdb = plt.subplots(figsize=(8, 8))
            im_cdb = ax_cdb.imshow(10 * np.log10(diff_frames[0] / d_max + 1e-12), cmap='turbo', vmin=-40, vmax=0, origin='lower', extent=ext)
            ax_cdb.set_title(f"{t_base} Change Detection dB")
            ax_cdb.set_xlabel("Range (m)")
            ax_cdb.set_ylabel("Azimuth (m)")
            plt.colorbar(im_cdb, ax=ax_cdb, label="Change (dB)")
            
            def update_cd_db(idx):
                im_cdb.set_data(10 * np.log10(diff_frames[idx] / d_max + 1e-12))
                return [im_cdb]
            
            ani_cdb = animation.FuncAnimation(fig_cdb, update_cd_db, frames=len(diff_frames), blit=True)
            ani_cdb.save(os.path.join(out_dir, "change_detection_db.gif"), writer='pillow', fps=fps, dpi=400)
            plt.close(fig_cdb)
            print("Saved change detection videos")
        
    print("Done!")
