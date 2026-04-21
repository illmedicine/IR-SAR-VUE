import sys
import os
import json
import numpy as np
import torch
import math
from scipy.special import j1

from city_targets import generate_city_scene, generate_inband_emitter
from view_city import render_city_view

# =============================================================================
# 1. MODULAR SIGINT MULTIBEAM CONFIGURATION
# =============================================================================
CFG = {
    'altitude_m': 350e3,             # 350 km
    'grazing_angle_deg': 90.0,       # 90 deg (Straight down nadir)
    'out_dir': 'SIGINT Sim Results',              
    'center_freq_hz': 2.0e9,         # 2 GHz center
    'bandwidth_hz': 1000e6,          # 1.5 GHz to 2.5 GHz
    
    'antenna_temp_k': 300.0,         
    'noise_figure_db': 3.5,          
    'other_losses_db': 3.0,          
    'rx_gain_max_dbi': 50.0,         # Max gain for each beam
    
    'area_size_m': (5000, 5000),     # 5km x 5km scene
    'num_beams_x': 202,              # Emulates exactly 10 step intervals of physical 4k element beam steering
    'num_beams_y': 202,
    'num_freq_bins': 25000,          # Increased back to 25,000 for perfect spectral bounds
    'integration_time_s': 60.0,      # 1 Minute Total Sweeping CPI
    
    'rng_seed': 42,
    # Completely disable radar scatterers, only use active emitters
    'num_clutter_pts': 0,            
    'num_people': 0,
    'num_wifi': 0,
    'num_cars': 0,
    'num_towers': 0,
    'num_jets': 0,
    'num_stealth_jets': 0,
    'num_inband_emitters': 0         # Handled dynamically below now
}

C = 299792458.0
K_B = 1.38064852e-23
Re = 6371000.0

if not os.path.exists(CFG['out_dir']):
    os.makedirs(CFG['out_dir'])

def generate_and_visualize_scene(scatter_area_m=None, num_emitters=2):
    if scatter_area_m is None:
        scatter_area_m = CFG['area_size_m'][0]
    print(f"Generating city scene (Tracking Area: {CFG['area_size_m'][0]}x{CFG['area_size_m'][1]}m, Scatter Area: {scatter_area_m}x{scatter_area_m}m)...")
    rng = np.random.default_rng(CFG['rng_seed'])
    
    # 3A. Base minimal objects (just roads/layout basically if any exist inherently)
    dynamic_objects = generate_city_scene(
        seed=CFG['rng_seed'],
        num_people=CFG['num_people'],
        num_wifi=CFG['num_wifi'],
        num_cars=CFG['num_cars'],
        num_towers=CFG['num_towers'],
        area_size=CFG['area_size_m'],
        satellite_grazing_angle_deg=CFG['grazing_angle_deg'],
        radar_center_freq_hz=CFG['center_freq_hz']
    )
    
    # Add In-Band Emitters exclusively
    PROTOCOLS = [
        # LTE B3 (1800 MHz)
        (1815e6, 20e6), (1835e6, 20e6), (1855e6, 20e6), 
        # LTE B2 (1900 MHz PCS)
        (1940e6, 20e6), (1960e6, 20e6), (1980e6, 20e6), 
        # LTE B1 (2100 MHz IMT)
        (2120e6, 20e6), (2140e6, 20e6), (2160e6, 20e6), 
        # LTE B40 (2300 MHz TDD)
        (2310e6, 20e6), (2330e6, 20e6), (2350e6, 20e6), (2370e6, 20e6), (2390e6, 20e6), 
        # Wi-Fi 2.4 GHz (Channels 1, 6, 11)
        (2412e6, 20e6), (2437e6, 20e6), (2462e6, 20e6), 
        # LTE B11/B74 (1500 MHz L-Band)
        (1480e6, 20e6), (1500e6, 20e6)
    ]
    
    print(f"Placing {num_emitters} standard emitters globally inside each of the {len(PROTOCOLS)} protocol bands natively...")
    for idx, chosen_proto in enumerate(PROTOCOLS):
        for sub_id in range(num_emitters):
            cx = rng.uniform(-scatter_area_m/2, scatter_area_m/2)
            cy = rng.uniform(-scatter_area_m/2, scatter_area_m/2)
            
            base_f_c = chosen_proto[0]
            proto_bw = chosen_proto[1]
            
            bw = rng.uniform(1.4e6, 5e6)
            max_shift = (proto_bw - bw) / 2.0
            f_c = base_f_c + rng.uniform(-max_shift, max_shift) if max_shift > 0 else base_f_c
            tx_power = 23.0 
                
            dynamic_objects.extend(generate_inband_emitter(
                (cx, cy, 0), name_prefix=f"EMI_Proto_{idx}_ID_{sub_id}",
                satellite_grazing_angle_deg=CFG['grazing_angle_deg'],
                rng=rng, radar_center_freq_hz=CFG['center_freq_hz'],
                center_freq_hz_override=f_c,
                bandwidth_hz_override=bw,
                tx_power_dbm_override=tx_power
            ))

    for t in dynamic_objects:
        if 'velocity' not in t:
            t['velocity'] = [0.0, 0.0, 0.0]
            
    timeline = [dynamic_objects]
    config_dict = {'area_size': CFG['area_size_m'], 'satellite_grazing_angle_deg': CFG['grazing_angle_deg']}
    dest_img = os.path.join(CFG['out_dir'], "city_view.png")
    render_city_view(config_dict, timeline, dest_img)
    return dynamic_objects

def calculate_multibeam_spectrum(targets):
    print("Calculating highly accurate GPU Phase History Multibeam Spectral Response Map with LEO Dynamics...")
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    print(f"Executing Time-Domain Stochastic Hardware Engine on Device: {device}")
    
    f_min = CFG['center_freq_hz'] - CFG['bandwidth_hz'] / 2.0
    f_max = CFG['center_freq_hz'] + CFG['bandwidth_hz'] / 2.0
    num_bins = CFG['num_freq_bins']
    freqs = np.linspace(f_min, f_max, num_bins)
    f_step = freqs[1] - freqs[0]
    FS = CFG['bandwidth_hz']
    num_samples = num_bins 
    
    emitters = [t for t in targets if t.get('is_emitter', False)]
    print(f"Found {len(emitters)} active emitters. Generating distinct physical PRN temporal streams...")
    
    x_beams = np.linspace(-CFG['area_size_m'][0]/2, CFG['area_size_m'][0]/2, CFG['num_beams_x'])
    y_beams = np.linspace(-CFG['area_size_m'][1]/2, CFG['area_size_m'][1]/2, CFG['num_beams_y'])
    
    G_max_lin = 10.0 ** (CFG['rx_gain_max_dbi'] / 10.0)
    central_lambda = C / CFG['center_freq_hz']
    D_antenna = central_lambda * np.sqrt(G_max_lin) / np.pi
    aperture_radius = D_antenna / 2.0
    
    pos_sat_0 = np.array([0.0, 0.0, CFG['altitude_m']])
    v_sat = np.array([0.0, 7500.0, 0.0]) # 7.5 km/s natively
    
    L_sys_lin = 10.0 ** (CFG['other_losses_db'] / 10.0)
    T_sys = CFG['antenna_temp_k'] + 290.0 * (10.0**(CFG['noise_figure_db']/10.0) - 1.0)
    Noise_per_bin_W = K_B * T_sys * f_step
    
    measured_power_mag2 = np.zeros((CFG['num_beams_y'], CFG['num_beams_x'], num_bins), dtype=np.float32)
    
    if len(emitters) > 0:
        e_pos = np.array([e['position'] for e in emitters])
        e_pwr_w = np.array([10.0 ** ((e['tx_power_dbm'] - 30.0) / 10.0) for e in emitters])
        e_gain_lin = np.array([10.0 ** (e.get('effective_tx_gain_dbi_to_sat', 0.0) / 10.0) for e in emitters])
        
        e_pos_t = torch.tensor(e_pos, device=device, dtype=torch.float64)
        
        fftfreqs = torch.fft.fftfreq(num_samples, d=1.0/FS, device=device)
        fftfreqs = torch.fft.fftshift(fftfreqs)
        
        e_masks = []
        for e in emitters:
            f_offset = e['freq_hz'] - CFG['center_freq_hz']
            bin_fmin = f_offset - e['bandwidth_hz'] / 2.0
            bin_fmax = f_offset + e['bandwidth_hz'] / 2.0
            mask = (fftfreqs >= bin_fmin) & (fftfreqs <= bin_fmax)
            e_masks.append(mask)
        e_masks_t = torch.stack(e_masks)
        
        e_pwr_t = torch.tensor(e_pwr_w, device=device, dtype=torch.float64).view(-1, 1)
        e_gain_t = torch.tensor(e_gain_lin, device=device, dtype=torch.float64).view(-1, 1)
        
    t_dwell_s = CFG['integration_time_s'] / (CFG['num_beams_x'] * CFG['num_beams_y'])
    N_sim_frames = 10 
    t_array = np.linspace(-CFG['integration_time_s']/2.0, CFG['integration_time_s']/2.0, N_sim_frames)
    time_bw_factor = (t_dwell_s * f_step) / N_sim_frames 
    
    print(f"Sweeping Phase History explicitly over {CFG['num_beams_x'] * CFG['num_beams_y']} continuous beams natively...")

    X_beams, Y_beams = np.meshgrid(x_beams, y_beams)
    
    frames_prn_t = []
    frames_phase_shifter = []
    frames_pos_sat_t = []
    with torch.no_grad():
        for f_idx in range(N_sim_frames):
            pos_sat_t = pos_sat_0 + v_sat * t_array[f_idx]
            pos_rx_t = torch.tensor(pos_sat_t, device=device, dtype=torch.float64).view(1, 3)
            frames_pos_sat_t.append(pos_rx_t)
            
            if len(emitters) > 0:
                dist_rx_emi = torch.norm(e_pos_t - pos_rx_t, dim=1)
                doppler_phase = -2.0 * np.pi * CFG['center_freq_hz'] * (dist_rx_emi / C)
                frames_phase_shifter.append(torch.exp(1j * doppler_phase).view(-1, 1))
                
                prn_f = (torch.randn((len(emitters), num_samples), device=device, dtype=torch.float64) + 
                         1j * torch.randn((len(emitters), num_samples), device=device, dtype=torch.float64)) / np.sqrt(2.0)
                prn_f_masked = prn_f * e_masks_t
                prn_t = torch.fft.ifft(torch.fft.ifftshift(prn_f_masked, dim=1), dim=1, norm="ortho")
                frames_prn_t.append(prn_t)
            else:
                frames_phase_shifter.append(None)
                frames_prn_t.append(None)

    # === COMPUTE DYNAMIC DIRTY PSF ===
    print("Computing rigorous smeared synthetic Dirty PSF kernel natively...")
    dirty_psf = torch.zeros((CFG['num_beams_y'], CFG['num_beams_x']), device=device, dtype=torch.float64)
    ghost_pos_t = torch.tensor([[0.0, 0.0, 0.0]], device=device, dtype=torch.float64) # Origin target natively
    ghost_pwr_w = 1.0 
    ghost_gain_t = torch.tensor([[1.0]], device=device, dtype=torch.float64)
    ghost_e_pwr_t = torch.tensor([[ghost_pwr_w]], device=device, dtype=torch.float64)
    
    with torch.no_grad():
        X_beams_t = torch.tensor(X_beams, device=device, dtype=torch.float64)
        Y_beams_t = torch.tensor(Y_beams, device=device, dtype=torch.float64)
        
        for f_idx in range(N_sim_frames):
            pos_rx_t = frames_pos_sat_t[f_idx]
            
            VB_x_psf = X_beams_t - pos_rx_t[0, 0]
            VB_y_psf = Y_beams_t - pos_rx_t[0, 1]
            VB_z_psf = torch.full_like(X_beams_t, -pos_rx_t[0, 2])
            
            VB_norm_psf = torch.sqrt(VB_x_psf**2 + VB_y_psf**2 + VB_z_psf**2)
            ub_tx = VB_x_psf / VB_norm_psf
            ub_ty = VB_y_psf / VB_norm_psf
            ub_tz = VB_z_psf / VB_norm_psf
            
            dist_rx_ghost = torch.norm(ghost_pos_t - pos_rx_t, dim=1)
            tgt_dir_ghost = (ghost_pos_t - pos_rx_t) / dist_rx_ghost.view(-1, 1) # (1, 3)
            
            cos_delta_psf = tgt_dir_ghost[0,0]*ub_tx + tgt_dir_ghost[0,1]*ub_ty + tgt_dir_ghost[0,2]*ub_tz
            cos_delta_psf = torch.clamp(cos_delta_psf, -1.0, 1.0)
            delta_psf = torch.acos(cos_delta_psf)
            
            ka = (2.0 * np.pi / central_lambda) * aperture_radius
            x_arg_cpu = (ka * torch.sin(delta_psf)).cpu().numpy()
            x_arg_safe = np.where(np.abs(x_arg_cpu) < 1e-6, 1e-6, x_arg_cpu)
            pattern_voltage = 2.0 * j1(x_arg_safe) / x_arg_safe
            rx_gain_lin_np = np.where(np.abs(x_arg_cpu) < 1e-6, G_max_lin, G_max_lin * (pattern_voltage ** 2))
            rx_gain_lin_psf = torch.tensor(rx_gain_lin_np, device=device, dtype=torch.float64)
            
            num_term_psf = ghost_e_pwr_t * ghost_gain_t * rx_gain_lin_psf * (central_lambda**2)
            den_term_psf = ((4.0 * np.pi)**2) * (dist_rx_ghost.view(-1, 1, 1)**2) * L_sys_lin
            
            dirty_psf += (num_term_psf / den_term_psf).squeeze(0) # (Ny, Nx)
            
    dirty_psf = dirty_psf / torch.max(dirty_psf)
    dirty_psf_np = dirty_psf.cpu().numpy()

    # Highly vectorized loop tracking dynamics dynamically across identically mapping frames
    with torch.no_grad():
        for yi in range(CFG['num_beams_y']):
            P_acc = torch.zeros((CFG['num_beams_x'], num_bins), device=device, dtype=torch.float32)
            noise_std = np.sqrt(Noise_per_bin_W / 2.0)
            
            for f_idx in range(N_sim_frames):
                if len(emitters) > 0:
                    pos_rx_t = frames_pos_sat_t[f_idx]
                    
                    VB_x = torch.tensor(X_beams[yi, :] - pos_rx_t[0, 0].item(), device=device, dtype=torch.float64) 
                    VB_y = torch.tensor(Y_beams[yi, :] - pos_rx_t[0, 1].item(), device=device, dtype=torch.float64) 
                    VB_z = torch.full_like(VB_x, -pos_rx_t[0, 2].item())
                    
                    VB_norm = torch.sqrt(VB_x**2 + VB_y**2 + VB_z**2)
                    ub_t = torch.stack([VB_x / VB_norm, VB_y / VB_norm, VB_z / VB_norm], dim=1) # (Nx, 3)
                    
                    dist_rx_emi = torch.norm(e_pos_t - pos_rx_t, dim=1)
                    tgt_dir_emi = (e_pos_t - pos_rx_t) / dist_rx_emi.view(-1, 1)
                    
                    cos_delta = torch.matmul(tgt_dir_emi, ub_t.T) # (N_emi, Nx)
                    cos_delta = torch.clamp(cos_delta, -1.0, 1.0)
                    delta = torch.acos(cos_delta)
                    
                    ka = (2.0 * np.pi / central_lambda) * aperture_radius
                    x_arg_cpu = (ka * torch.sin(delta)).cpu().numpy()
                    
                    x_arg_safe = np.where(np.abs(x_arg_cpu) < 1e-6, 1e-6, x_arg_cpu)
                    pattern_voltage = 2.0 * j1(x_arg_safe) / x_arg_safe
                    
                    rx_gain_lin_np = np.where(np.abs(x_arg_cpu) < 1e-6, G_max_lin, G_max_lin * (pattern_voltage ** 2))
                    rx_gain_lin = torch.tensor(rx_gain_lin_np, device=device, dtype=torch.float64) # (N_emi, Nx)
                    
                    num_term_emi = e_pwr_t * e_gain_t * rx_gain_lin * (central_lambda**2)
                    den_term_emi = ((4.0 * np.pi)**2) * (dist_rx_emi.view(-1, 1)**2) * L_sys_lin
                    scale_factors = torch.sqrt(num_term_emi / den_term_emi) # (N_emi, Nx)
                    
                    prn_t_shifted = frames_prn_t[f_idx] * frames_phase_shifter[f_idx]
                    pulse_sig = torch.einsum('en,es->ns', scale_factors.to(torch.complex128), prn_t_shifted)
                else:
                    pulse_sig = torch.zeros((CFG['num_beams_x'], num_samples), device=device, dtype=torch.complex128)
                
                pulse_f = torch.fft.fftshift(torch.fft.fft(pulse_sig, dim=1, norm="ortho"), dim=1)
                
                noise_f = (torch.randn((CFG['num_beams_x'], num_samples), device=device, dtype=torch.float32) + 
                           1j * torch.randn((CFG['num_beams_x'], num_samples), device=device, dtype=torch.float32)) * noise_std
                           
                # Abs squared implicitly maps into bounds smoothly
                P_acc += torch.abs(pulse_f + noise_f.to(pulse_f.dtype))**2 
            
            P_acc = P_acc * (time_bw_factor / N_sim_frames)
            measured_power_mag2[yi, :, :] = P_acc.cpu().numpy()
                
    emitters_gt = [{'x': e['position'][0], 'y': e['position'][1], 'f': e['freq_hz'], 'bw': e['bandwidth_hz']} for e in emitters]
    
    out_path = os.path.join(CFG['out_dir'], "sigint_multibeam_data.npz")
    np.savez(out_path, 
             measured_power_mag2=measured_power_mag2,
             x_beams=x_beams,
             y_beams=y_beams,
             freqs=freqs,
             aperture_radius=aperture_radius,
             alt=CFG['altitude_m'],
             dirty_psf=dirty_psf_np,
             emitters_gt=json.dumps(emitters_gt)
            )
            
    print(f"Phase History simulation complete natively! Physical array saved! Output size: {measured_power_mag2.nbytes / 1e6:.2f} MB")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--area_size', type=float, default=5000.0)
    parser.add_argument('--scatter_area', type=float, default=None)
    parser.add_argument('--emitters', type=int, default=2)
    args = parser.parse_args()
    
    CFG['area_size_m'] = [args.area_size, args.area_size]
    targets = generate_and_visualize_scene(args.scatter_area, args.emitters)
    calculate_multibeam_spectrum(targets)
