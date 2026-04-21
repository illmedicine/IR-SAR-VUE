import sys
import os
import json
import numpy as np
import torch
import math

from city_targets import generate_city_scene, interpolate_rcs_scale
from view_city import render_city_view

# =============================================================================
# 1. MODULAR SAR SIMULATION CONFIGURATION
# =============================================================================
CFG = {
    # --- ORBIT & GEOMETRY ---
    'altitude_m': 350e3,             # 350 km
    'grazing_angle_deg': 50.0,       # 50 deg
    'squint_angle_deg': 0.0,         # 0 deg
    'sar_mode': 'spotlight',         # 'stripmap' or 'spotlight'
    'scene_center_m': [0.0, 0.0, 0.0], # 3D Tracking center coordinate
    'earth_rotation_mode': 'compensated', # 'compensated', 'uncompensated', None
    'scene_lat_deg': 40.0,           # Latitude of scene center (40N)
    'orbit_heading_deg': 349.0,      # Flight path angle vs True North (e.g., 349 = NNW)
    
    # --- RF PARAMETERS (Matches SAR_Visualizer defaults) ---
    'tx_enabled': True,              # If False, radar is passive (listen-only SIGINT mode)
    'center_freq_hz': 2.0e9,         # 2 GHz
    'bandwidth_hz': 500e6,           # 500 MHz
    'tx_power_w': 20000.0,           # 20000 W peak per beam
    'antenna_temp_k': 300.0,         # 300K mapped directly from Antenna Temp
    'noise_figure_db': 3.5,          # 3.5 dB Receiver Noise Figure
    'other_losses_db': 3.0,          # 3 dB system loss
    
    # --- ANTENNA ---
    'antenna_gain_az_dbi': 23.0,     # Azimuth gain
    'antenna_gain_el_dbi': 23.0,     # Elevation gain
    
    # --- TIMING & WAVEFORM ---
    'waveform_type': 'OFDM',          # OFDM subcarriers
    'ofdm_subcarrier_bw_hz': 500e3,   # 500 kHz OFDM carrier spacing default
    'prf_hz': 8000.0,                # 8000 Hz Pulse Repetition Freq
    'duty_cycle_pct': 20.0,          # 20%
    'cpi_sec': 3.0,                  # Coherent processing interval length
    
    # --- HRWS / MULTI-CHANNEL DBF ---
    'hrws_mode': False,               # Disable HRWS for simple spotlight test
    'is_bistatic': False,            # Tx and Rx are strictly separate craft?
    'num_rx_antennas': 1,            # Only 1 channel
    'rx_spacing_m': 'dpca',          # Physical distance (float), list of explicit offsets [m], or 'dpca'
    'max_sub_beam_gain_dbi': 50.0,   # Maximum synthesized sub-beam gain threshold
    'apply_rx_bandpass_filter': True, # Perfectly reject out-of-band energy
    
    # --- SCORE (Scan-On-Receive) ---
    'score_mode': False,             # Enable dynamic Rx elevation sweeping
    'score_rx_gain_el_dbi': 23.0,    # High directivity Rx elevation pencil-beam gain
    'score_scan_ahead_m': 3000.0,    # Scan 3000m ahead of ground echo to capture aircraft layover
    
    # --- SCENE GENERATION (City Targets) ---
    'rng_seed': 42,
    'area_size_m': (1000, 1000),     # 1km x 1km scene
    'sigma_zero': 0.05,              # Average suburban background
    'num_clutter_pts': 10000,        # Number of statistical scatterers (Stay < 50k for VRAM)
    'num_people': 0,
    'num_wifi': 0,
    'num_cars': 30,
    'num_towers': 0,
    'num_jets': 1,
    'num_stealth_jets': 1
}

import json
import os

if os.path.exists("batch_override.json"):
    print("Loading global definitions from batch_override.json!")
    with open("batch_override.json", "r") as f:
        override = json.load(f)
        CFG.update(override)

# =============================================================================
# 2. CONSTANTS & DERIVED PARAMETERS
# =============================================================================
C = 299792458.0
Re = 6371000.0
GM = 3.986004418e14
K_B = 1.38064852e-23 # Boltzmann constant

R_sat = Re + CFG['altitude_m']
V_sat = np.sqrt(GM / R_sat)

LAMBDA = C / CFG['center_freq_hz']
PULSE_WIDTH = (CFG['duty_cycle_pct'] / 100.0) / CFG['prf_hz']

# =============================================================================
# ARBITRARY WAVEFORM GENERATOR
# =============================================================================
M_res = 100000
t_base = np.linspace(0, PULSE_WIDTH, M_res, endpoint=False)

if CFG['waveform_type'] == 'LFM':
    k_rate = CFG['bandwidth_hz'] / PULSE_WIDTH
    tx_baseband = np.exp(1j * np.pi * k_rate * (t_base - PULSE_WIDTH/2)**2)
elif CFG['waveform_type'] == 'NLFM':
    # Cubic phase spectral tapering (Non-Linear Frequency Modulation)
    # Designed to slow sweep at band-center, enhancing spectral shape and suppressing sidelobes natively
    alpha_nlfm = 0.5 # 50% slower sweep at center frequency
    c1 = alpha_nlfm * CFG['bandwidth_hz'] / PULSE_WIDTH
    c3 = 4.0 * CFG['bandwidth_hz'] * (1.0 - alpha_nlfm) / (PULSE_WIDTH**3)
    t_centered = t_base - PULSE_WIDTH/2
    phase_nlfm = np.pi * c1 * (t_centered**2) + (np.pi / 2.0) * c3 * (t_centered**4)
    tx_baseband = np.exp(1j * phase_nlfm)
elif CFG['waveform_type'] == 'PhaseCoded':
    rng_wf = np.random.default_rng(42)
    N_chips = int(CFG['bandwidth_hz'] * PULSE_WIDTH)
    prn_code_np = np.pi * rng_wf.integers(0, 2, size=N_chips).astype(np.float64)
    chip_idx = np.floor((t_base / PULSE_WIDTH) * N_chips).astype(int)
    chip_idx = np.clip(chip_idx, 0, N_chips - 1)
    tx_baseband = np.exp(1j * prn_code_np[chip_idx])
elif CFG['waveform_type'] == 'OFDM':
    # OFDM waveform generation is deferred to after scene creation
    # so null bands can be auto-extracted from the actual emitter frequencies.
    # Placeholder — will be overwritten by generate_ofdm_waveform() below.
    tx_baseband = np.ones(M_res, dtype=np.complex128)
    
    # Peak normalize
    pass  # Normalization done in generate_ofdm_waveform()
else:
    tx_baseband = np.zeros(M_res, dtype=np.complex128)
tx_baseband = tx_baseband.astype(np.complex64)
FS = max(CFG['bandwidth_hz'] * 1.2, 300e6) # 20% oversampling baseband

def generate_ofdm_waveform(targets):
    """
    Generate robust OFDM waveform with independent QPSK symbols to avoid periodic grating lobes,
    and nulls subcarriers based on actual scene emitters.
    Returns the new tx_baseband (complex64).
    """
    global tx_baseband
    
    # Auto-extract null bands from scene emitters
    null_bands = []
    radar_lo = CFG['center_freq_hz'] - CFG['bandwidth_hz'] / 2
    radar_hi = CFG['center_freq_hz'] + CFG['bandwidth_hz'] / 2
    for t in targets:
        if t.get('is_emitter', False):
            ef = t['freq_hz']
            ebw = t['bandwidth_hz']
            if ef + ebw/2 > radar_lo and ef - ebw/2 < radar_hi:
                null_bands.append([ef, ebw])
    
    # Also include any manually specified null bands
    for nb in CFG.get('ofdm_null_bands', []):
        null_bands.append([nb[0], nb[1]])
        
    bandwidth_hz = CFG['bandwidth_hz']
    pulse_width = PULSE_WIDTH
    subcarrier_bw_hz = CFG.get('ofdm_subcarrier_bw_hz', 200000.0) # default or config override
    
    N_carriers = int(np.round(bandwidth_hz / subcarrier_bw_hz))
    freqs = np.linspace(-bandwidth_hz/2, bandwidth_hz/2, N_carriers)
    
    T_sym = 1.0 / subcarrier_bw_hz
    N_sym = int(np.ceil(pulse_width / T_sym))
    
    rng_wf = np.random.default_rng(42)
    tx_new = np.zeros(M_res, dtype=np.complex128)
    center_freq = CFG['center_freq_hz']
    
    valid_carriers = []
    nulled_count = 0
    for k, f_k in enumerate(freqs):
        f_abs = center_freq + f_k
        is_nulled = False
        for nb in null_bands:
            if abs(f_abs - nb[0]) <= nb[1] / 2.0:
                is_nulled = True
                break
        if is_nulled:
            nulled_count += 1
        else:
            valid_carriers.append((k, f_k))
            
    # Generate symbol by symbol
    sym_len_samples = int(np.round(T_sym / pulse_width * M_res))
    
    for s_i in range(N_sym):
        start_idx = s_i * sym_len_samples
        end_idx = min((s_i + 1) * sym_len_samples, M_res)
        if start_idx >= M_res: break
            
        t_sym = t_base[start_idx:end_idx]
        tx_sym = np.zeros(end_idx - start_idx, dtype=np.complex128)
        
        phases = rng_wf.choice([0, np.pi/2, np.pi, 3*np.pi/2], size=len(valid_carriers))
        for i, (k, f_k) in enumerate(valid_carriers):
            tx_sym += np.exp(1j * phases[i]) * np.exp(1j * 2 * np.pi * f_k * t_sym)
            
        tx_new[start_idx:end_idx] = tx_sym
        
    # RMS Normalization (matches LFM unit power, crucial for SAR processing gain)
    rms = np.sqrt(np.mean(np.abs(tx_new)**2))
    if rms > 0:
        tx_baseband = (tx_new / rms).astype(np.complex64)
    else:
        tx_baseband = tx_new.astype(np.complex64)
        
    nulled_bw_mhz = sum(nb[1] for nb in null_bands) / 1e6
    print(f"OFDM Waveform (Robust): {N_carriers} subcarriers @ {subcarrier_bw_hz/1e3:.1f} kHz spacing | Symbols: {N_sym}")
    print(f"  Nulled: {nulled_count}/{N_carriers} subcarriers ({100*nulled_count/N_carriers:.1f}%) across {len(null_bands)} emitter channels (~{nulled_bw_mhz:.0f} MHz)")
    for nb in null_bands:
        print(f"    Null: {nb[0]/1e6:.1f} MHz ± {nb[1]/1e6/2:.1f} MHz")
        
    return tx_baseband

theta_look_rad = np.radians(90.0 - CFG['grazing_angle_deg'])
# If scene_alt_m is set, shift the reference surface to that altitude for R0 calculation
# This centers the receive window on elevated targets (e.g., warheads at 100km)
R_scene = Re + CFG.get('scene_alt_m', 0.0)
theta_inc_rad = np.arcsin((R_sat / R_scene) * np.sin(theta_look_rad))
gamma_rad = theta_inc_rad - theta_look_rad
R0 = np.sqrt(R_scene**2 + R_sat**2 - 2 * R_scene * R_sat * np.cos(gamma_rad))

# System Gains and Losses
G_tx_lin = 10.0**(CFG['antenna_gain_az_dbi']/10.0) * 10.0**(CFG['antenna_gain_el_dbi']/10.0)
G_rx_lin = G_tx_lin # Assuming identical Tx/Rx antennas for now

# ---- Atmospheric, Rain & Ionospheric Losses (ITU-R P.676-12 / P.838) ----
f_ghz = CFG['center_freq_hz'] / 1e9

# O₂ zenith one-way attenuation (dB) — ITU-R P.676-12 Fig 4/11
_fO2 = np.array([0.3,1,2,3,5,8,10,12,15,18,20,22,23,25,28,30,32,35,38,40,
                 42,44,46,48,50,51,52,53,54,55,56,57,58,59,59.5,60,60.5,61,
                 62,63,64,65,66,67,68,70,72,75,80,85,90,95,100,105,110,115,
                 117,118,118.75,119,120,122,125,130,135,140,145,150])
_aO2 = np.array([0.002,0.003,0.004,0.005,0.006,0.009,0.013,0.018,0.026,0.035,
                 0.040,0.044,0.046,0.048,0.053,0.058,0.063,0.073,0.090,0.11,
                 0.14,0.18,0.25,0.37,0.58,0.75,1.0,1.5,2.2,3.8,7.0,14,28,60,
                 120,260,120,60,25,12,6.5,3.8,2.2,1.5,1.0,0.55,0.35,0.20,0.10,
                 0.065,0.048,0.042,0.040,0.042,0.050,0.080,0.18,0.50,3.0,0.50,
                 0.18,0.085,0.055,0.040,0.035,0.038,0.045,0.055])

# H₂O zenith one-way attenuation (dB) — standard atmosphere 7.5 g/m³
_fH2O = np.array([0.3,1,2,3,5,8,10,12,15,18,19,20,21,22,22.235,22.5,23,24,25,
                  28,30,35,40,45,50,60,70,80,90,100,110,120,130,140,150])
_aH2O = np.array([0.0001,0.0002,0.0005,0.001,0.002,0.004,0.008,0.013,0.025,
                  0.055,0.075,0.10,0.15,0.26,0.32,0.26,0.18,0.095,0.065,0.035,
                  0.028,0.023,0.025,0.030,0.035,0.040,0.038,0.040,0.045,0.055,
                  0.070,0.10,0.12,0.15,0.20])

zenith_O2 = np.interp(f_ghz, _fO2, _aO2)
zenith_H2O = np.interp(f_ghz, _fH2O, _aH2O)  # standard (clear) weather
zenith_gas = zenith_O2 + zenith_H2O

# Ionospheric loss (TEC ~40 TECU, only significant below ~2 GHz)
zenith_iono = 0.04 * (1.0 / max(f_ghz, 0.1))**1.5

true_grazing_rad = (np.pi / 2.0) - theta_inc_rad
slant_mult = 1.0 / max(np.sin(true_grazing_rad), 0.017)

loss_gas_db  = 2.0 * zenith_gas * slant_mult
loss_iono_db = 2.0 * zenith_iono * slant_mult
total_atmos_iono_db = loss_gas_db + loss_iono_db

L_sys_lin = 10.0**((CFG['other_losses_db'] + total_atmos_iono_db) / 10.0)

# HRWS Physical Constraints
if CFG.get('hrws_mode', False):
    sub_beam_gain_dbi = CFG['antenna_gain_az_dbi'] + CFG['antenna_gain_el_dbi']
    if sub_beam_gain_dbi > CFG['max_sub_beam_gain_dbi']:
        raise ValueError(f"Calculated DBF Sub-Beam Gain ({sub_beam_gain_dbi} dB) strictly exceeds the hardware envelope max limit ({CFG['max_sub_beam_gain_dbi']} dB).")

# =============================================================================
# 3. AUTO-GENERATE CITY SCENE
# =============================================================================
def generate_and_visualize_scene():
    print(f"Generating city scene (Area: {CFG['area_size_m'][0]}x{CFG['area_size_m'][1]}m)...")
    
    # Set up global random number generator
    rng = np.random.default_rng(CFG['rng_seed'])
    
    # 3A. Call the procedural generator from city_targets.py
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
    
    # Add Jets
    from city_targets import generate_fighter_jet, generate_stealth_fighter, generate_ballistic_warhead, generate_person_only, generate_inband_emitter
    for i in range(CFG['num_jets']):
        targets = generate_fighter_jet(center_pos=(0, 0, 0), name_prefix=f"Jet_{i}", radar_center_freq_hz=CFG['center_freq_hz'])
        
        speed = 250.0  # cruising speed
        heading = rng.uniform(0, 2 * np.pi)
        vx = speed * np.cos(heading)
        vy = speed * np.sin(heading)
        jet_cx = rng.uniform(-CFG['area_size_m'][0]/2, CFG['area_size_m'][0]/2)
        jet_cy = rng.uniform(-CFG['area_size_m'][1]/2, CFG['area_size_m'][1]/2)
        
        # Add high altitude, position translation and speed
        for t in targets:
            t['position'][0] += jet_cx
            t['position'][1] += jet_cy
            t['position'][2] += CFG.get('jet_alt_m', 1000.0)
            t['velocity'] = CFG.get('jet_vel_m_s', [float(vx), float(vy), 0.0])
        dynamic_objects.extend(targets)
        
    for i in range(CFG['num_stealth_jets']):
        targets = generate_stealth_fighter(center_pos=(0, 0, 500), name_prefix=f"StealthJet_{i}", radar_center_freq_hz=CFG['center_freq_hz'])
        for t in targets:
            t['position'][2] += CFG.get('stealth_alt_m', 5500.0)
            t['velocity'] = CFG.get('stealth_vel_m_s', [0.0, 300.0, 0.0])
        dynamic_objects.extend(targets)
    
    # Add Ballistic Warheads
    for i in range(CFG.get('num_warheads', 0)):
        targets = generate_ballistic_warhead(center_pos=(0, 0, 0), name_prefix=f"Warhead_{i}", radar_center_freq_hz=CFG['center_freq_hz'])
        for t in targets:
            t['position'][2] += CFG.get('warhead_alt_m', 100000.0)
            t['velocity'] = CFG.get('warhead_vel_m_s', [3430.0, 0.0, 0.0])
        dynamic_objects.extend(targets)
    
    # Add People-Only (no cell phone emitter)
    num_people_only = CFG.get('num_people_only', 0)
    if num_people_only > 0:
        for i in range(num_people_only):
            cx = rng.uniform(-CFG['area_size_m'][0]/2, CFG['area_size_m'][0]/2)
            cy = rng.uniform(-CFG['area_size_m'][1]/2, CFG['area_size_m'][1]/2)
            speed = CFG.get('human_speed_m_s', rng.uniform(1.0, 1.8))
            heading = rng.uniform(0, 2 * np.pi)
            vx = speed * np.cos(heading)
            vy = speed * np.sin(heading)
            pts = generate_person_only(center_pos=(cx, cy, 0), name_prefix=f"Human_{i}", radar_center_freq_hz=CFG['center_freq_hz'])
            for t in pts:
                t['velocity'] = [float(vx), float(vy), 0.0]
            dynamic_objects.extend(pts)
    
    # Add In-Band Emitters (hardcoded in 1750-2250 MHz passband)
    num_inband = CFG.get('num_inband_emitters', 0)
    if num_inband > 0:
        for i in range(num_inband):
            cx = rng.uniform(-CFG['area_size_m'][0]/2, CFG['area_size_m'][0]/2)
            cy = rng.uniform(-CFG['area_size_m'][1]/2, CFG['area_size_m'][1]/2)
            dynamic_objects.extend(generate_inband_emitter(
                (cx, cy, 0), name_prefix=f"InBand_{i}",
                satellite_grazing_angle_deg=CFG['grazing_angle_deg'],
                rng=rng, radar_center_freq_hz=CFG['center_freq_hz'],
                tx_power_dbm_override=CFG.get('tx_power_dbm_override'),
                bandwidth_hz_override=CFG.get('bandwidth_hz_override'),
                center_freq_hz_override=CFG.get('center_freq_hz_override')
            ))

    # 3B. Generate deterministic statistical clutter mathematically mapped to sigma_zero
    clutter_scale = interpolate_rcs_scale('standard', CFG['center_freq_hz'])
    total_area = CFG['area_size_m'][0] * CFG['area_size_m'][1]
    expected_clutter_rcs = total_area * CFG['sigma_zero'] * clutter_scale
    mean_rcs = expected_clutter_rcs / CFG['num_clutter_pts']
    
    print(f"Distributing {CFG['num_clutter_pts']} background scatterers (Total RCS: {expected_clutter_rcs:.1f} m^2)...")
    c_x = rng.uniform(-CFG['area_size_m'][0]/2, CFG['area_size_m'][0]/2, CFG['num_clutter_pts'])
    c_y = rng.uniform(-CFG['area_size_m'][1]/2, CFG['area_size_m'][1]/2, CFG['num_clutter_pts'])
    c_rcs = rng.exponential(mean_rcs, CFG['num_clutter_pts'])
    
    clutter_targets = []
    for i in range(CFG['num_clutter_pts']):
        clutter_targets.append({
            'name': f"clutter_{i}",
            'type': 'clutter',
            'position': [c_x[i], c_y[i], 0.0],
            'rcs': c_rcs[i]
        })
        
    all_targets = dynamic_objects + clutter_targets
    
    # 3B.5 Ensure all targets have a velocity vector before visualization 
    for t in all_targets:
        if 'velocity' not in t:
            t['velocity'] = [0.0, 0.0, 0.0]
            
    # 3C. Wrap in JSON timeline format for Visualizer
    timeline = [all_targets]
    
    # 3D. Trigger Visualizer PNG
    config_dict = {'area_size': CFG['area_size_m'], 'satellite_grazing_angle_deg': CFG['grazing_angle_deg']}
    dest_img = os.path.join(CFG.get('out_dir', ''), "city_view.png") if CFG.get('out_dir', '') else "city_view.png"
    render_city_view(config_dict, timeline, dest_img)
    
    return all_targets

# =============================================================================
# 4. ORBITAL MECHANICS & TRAJECTORY 
# =============================================================================
def calculate_trajectories(num_pulses, t_vec):
    """
    Computes precise world-coordinate 3D positions of the Satellite platform.
    """
    print("Calculating orbital flight paths...")
    omega = V_sat / R_sat
    sin_g = np.sin(gamma_rad)
    cos_g = np.cos(gamma_rad)
    
    S0_from_C = np.array([-R_sat * sin_g, 0, R_sat * cos_g])
    V_unit = np.array([0.0, 1.0, 0.0]) # Orbit along the Y axis
    C_offset = np.array([0, 0, -Re])   # Center scene at origin
    
    pos_tx = np.zeros((num_pulses, 3))
    vel_tx = np.zeros((num_pulses, 3))
    
    for i, t in enumerate(t_vec):
        wt = omega * t
        P_vec = S0_from_C * np.cos(wt) + (R_sat * V_unit) * np.sin(wt)
        V_vec = (V_sat * V_unit) * np.cos(wt) - (S0_from_C * omega) * np.sin(wt)
        pos_tx[i] = P_vec + C_offset
        vel_tx[i] = V_vec
        
    # Pre-compute independent receive channels
    rx_positions = []
    
    # Check for auto-DPCA rigid baseline condition
    spacing_val = CFG['rx_spacing_m']
    if str(spacing_val).lower() == 'dpca':
        # DPCA Strict 1-pulse spacing between adjacent phase centers: d = 2 * v / PRF
        spacing_val = (2.0 * V_sat) / CFG['prf_hz']
        print(f"  Auto-Calculated DPCA Uniform Condition Phase Center Spacing: {spacing_val:.4f} m")
        
    if (CFG.get('is_bistatic', False) or CFG.get('hrws_mode', False)) and CFG['num_rx_antennas'] > 1:
        # Phase centers separated by spacing_val (lever arm)
        for rx_idx in range(CFG['num_rx_antennas']):
            if isinstance(spacing_val, list):
                # Pull exact physical offset if list is provided
                offset = float(spacing_val[rx_idx]) if rx_idx < len(spacing_val) else 0.0
            else:
                # Calculate simple uniform spacing
                offset = (rx_idx - (CFG['num_rx_antennas'] - 1) / 2.0) * float(spacing_val)
                
            # Assume separation is strictly along-track
            pos_rx = np.copy(pos_tx)
            # Offset pos_rx along the velocity vector precisely
            for i in range(num_pulses):
                v_dir = vel_tx[i] / np.linalg.norm(vel_tx[i])
                pos_rx[i] = pos_tx[i] + v_dir * offset
            rx_positions.append(pos_rx)
    else:
        # Monostatic or single Rx bistatic (colocated for phase math purposes unless offset)
        rx_positions.append(np.copy(pos_tx))

    return pos_tx, vel_tx, rx_positions

# =============================================================================
# 5. GPU PHASE HISTORY ENGINE
# =============================================================================
@torch.no_grad()
def simulate_raw_phase_history(targets, t_vec, pos_tx_np, vel_tx_np, pos_rx_channel_np, tx_baseband=None):
    """
    Stripped down, extremely fast GPU physics generator.
    Produces raw baseband IQ phase delays without focusing.
    """
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    print(f"Simulating Fast-Time Phase History on Device: {device}")
    
    # Isolate Point Targets vs Emitters
    pt_targets = [t for t in targets if not t.get('is_emitter', False)]
    pt_emitters = [t for t in targets if t.get('is_emitter', False)]
    
    target_pos_0 = np.array([t['position'] for t in pt_targets])
    target_vel_0 = np.array([t.get('velocity', [0.0, 0.0, 0.0]) for t in pt_targets])
    target_rcs = np.array([t['rcs'] for t in pt_targets])
    
    print(f"Processing physics for {len(pt_targets)} point targets...")
    
    # --- Earth Rotation & Doppler Yaw Steering Engine ---
    if CFG['earth_rotation_mode'] is not None and CFG['earth_rotation_mode'].lower() != 'none':
        W_E = 7.292115e-5 # rad/s Earth rotation rate
        R_E = 6371000.0   # meters Earth radius
        
        scene_lat = CFG['scene_lat_deg']
        H_rad = np.radians(CFG['orbit_heading_deg'])
        
        # In our [X(Right), Y(Fwd), Z(Up)] tangent plane:
        # True North = [-sin(H), cos(H), 0]
        # True East  = [cos(H), sin(H), 0]
        east_vec = np.array([np.cos(H_rad), np.sin(H_rad), 0.0])
        
        def calc_earth_vel(pos_array):
            if len(pos_array) == 0: return np.zeros_like(pos_array)
            # Distance North = Y * cos(H) - X * sin(H)
            dist_north = pos_array[:, 1] * np.cos(H_rad) - pos_array[:, 0] * np.sin(H_rad)
            # 1 deg latitude ~ 111.32 km
            target_lats = scene_lat + (dist_north / (np.pi * R_E / 180.0))
            v_mag = W_E * R_E * np.cos(np.radians(target_lats))
            return np.outer(v_mag, east_vec)
            
        # Base compensation (Zero-Doppler Yaw Steering matching Scene Center)
        if CFG['earth_rotation_mode'] == 'compensated':
            v_earth_center_mag = W_E * R_E * np.cos(np.radians(scene_lat))
            v_compensate = v_earth_center_mag * east_vec
            print(f"  Applied Yaw Steering Compensation: {v_compensate} m/s")
        else:
            v_compensate = np.array([0.0, 0.0, 0.0])
            print("  Earth Rotation active but UNCOMPENSATED. Huge Doppler centroid expected.")
            
        # Apply physics to Targets
        v_earth_targets = calc_earth_vel(target_pos_0)
        target_vel_0 = target_vel_0 + v_earth_targets - v_compensate
        
    # Fast time vector setup (Capture 1.2x Pulse Width + target ranges)
    # R0 is center swath distance
    swath_depth_sec = (CFG['area_size_m'][0] * np.sin(theta_inc_rad)) / C
    
    # Account for elevated targets (jets/aircraft at altitude) that are closer in slant range
    max_alt = CFG.get('max_target_alt_m', 0.0)
    alt_range_offset = max_alt * np.cos(np.radians(CFG['grazing_angle_deg']))
    alt_time_offset = 2.0 * alt_range_offset / C  # round-trip time difference
    
    total_window = PULSE_WIDTH * 1.5 + swath_depth_sec * 3.0 + alt_time_offset * 1.5
    num_samples = int(total_window * FS)
    
    # Pre-allocate output
    t_start_fast = (2 * R0 / C) - (PULSE_WIDTH/1.5) - swath_depth_sec - alt_time_offset * 1.2
    fast_times = np.linspace(0, num_samples/FS, num_samples)
    t_fast_abs = t_start_fast + fast_times
    k_rate = CFG['bandwidth_hz'] / PULSE_WIDTH
    
    # Upload vectors to Device
    pos_tx_t = torch.tensor(pos_tx_np, device=device, dtype=torch.float64) 
    vel_tx_t = torch.tensor(vel_tx_np, device=device, dtype=torch.float64) 
    pos_rx_t = torch.tensor(pos_rx_channel_np, device=device, dtype=torch.float64) 
    t_vec_t = torch.tensor(t_vec, device=device, dtype=torch.float64)
    
    t_pos_0_t = torch.tensor(target_pos_0, device=device, dtype=torch.float64) 
    t_vel_0_t = torch.tensor(target_vel_0, device=device, dtype=torch.float64)
    t_rcs_t = torch.tensor(target_rcs, device=device, dtype=torch.float64).view(1, -1, 1) 
    
    # Emitter Setup (Pre-calculate Spectral Masks for PRN Synthesis)
    has_emi = len(pt_emitters) > 0
    if has_emi:
        print(f"Tracking {len(pt_emitters)} active RF emitters for complex EMI PRN synthesis...")
        e_pos_0 = np.array([e['position'] for e in pt_emitters])
        e_vel_0 = np.array([e.get('velocity', [0.0, 0.0, 0.0]) for e in pt_emitters])
        
        # Apply Earth Rotation to Emitters as well
        if CFG['earth_rotation_mode'] is not None and CFG['earth_rotation_mode'].lower() != 'none':
            v_earth_em = calc_earth_vel(e_pos_0)
            e_vel_0 = e_vel_0 + v_earth_em - v_compensate
            
        e_pwr_w_list = [(10**((e['tx_power_dbm'] - 30.0) / 10.0)) for e in pt_emitters]
        e_gain_lin_list = [10**(e['effective_tx_gain_dbi_to_sat'] / 10.0) for e in pt_emitters]
        
        fs = CFG['bandwidth_hz']
        # Compute frequency bins for the FFT (zero-centered)
        freqs = torch.fft.fftfreq(num_samples, d=1.0/fs, device=device)
        freqs = torch.fft.fftshift(freqs)
        
        e_masks = []
        for e in pt_emitters:
            f_offset = e['freq_hz'] - CFG['center_freq_hz']
            em_bw = e['bandwidth_hz']
            
            rx_fmin = -CFG['bandwidth_hz'] / 2.0
            rx_fmax = CFG['bandwidth_hz'] / 2.0
            em_fmin = f_offset - em_bw / 2.0
            em_fmax = f_offset + em_bw / 2.0
            
            if CFG['apply_rx_bandpass_filter']:
                bin_fmin = max(rx_fmin, em_fmin)
                bin_fmax = min(rx_fmax, em_fmax)
            else:
                bin_fmin = em_fmin
                bin_fmax = em_fmax
                
            mask = (freqs >= bin_fmin) & (freqs <= bin_fmax)
            e_masks.append(mask)
            
        e_pos_t = torch.tensor(e_pos_0, device=device, dtype=torch.float64)
        e_vel_t = torch.tensor(e_vel_0, device=device, dtype=torch.float64)
        e_pwr_t = torch.tensor(e_pwr_w_list, device=device, dtype=torch.float64)
        e_gain_t = torch.tensor(e_gain_lin_list, device=device, dtype=torch.float64)
        e_masks_t = torch.stack(e_masks) # Shape: (num_emitters, num_samples)

    t_fast_t = torch.tensor(t_fast_abs, device=device, dtype=torch.float64).view(1, 1, -1)
    
    # Allocate Output Matrix
    raw_sig = torch.zeros((len(t_vec), num_samples), device='cpu', dtype=torch.complex128)
    
    # Process targets in chunks to avoid GPU OOM (25,000 targets * 26,000 samples = ~10GB per pulse!)
    MAX_TARGETS_PER_BATCH = 2000
    num_targets = len(pt_targets)
    
    if tx_baseband is not None and len(tx_baseband) > 0:
        tx_baseband_t = torch.tensor(tx_baseband, device=device, dtype=torch.complex64)
        M_res = len(tx_baseband)
        
    # Run loop over slow time (pulses)
    for i in range(len(t_vec)):
        if i % 100 == 0:
            sys.stdout.write(f"\r  Pulse {i}/{len(t_vec)}")
            sys.stdout.flush()
            
        t_curr = t_vec_t[i]
        
        # Tx/Rx are single 1x3 vectors
        p_tx = pos_tx_t[i].view(1, 3) 
        v_tx = vel_tx_t[i].view(1, 3)
        p_rx = pos_rx_t[i].view(1, 3)
        
        # We will accumulate the signal for this pulse
        pulse_sig = torch.zeros(num_samples, device=device, dtype=torch.complex64)
        
        if CFG['tx_enabled']:
            # Batch over targets
            for b_start in range(0, num_targets, MAX_TARGETS_PER_BATCH):
                b_end = min(b_start + MAX_TARGETS_PER_BATCH, num_targets)
                
                # Slice Target Data
                t_pos_0_b = t_pos_0_t[b_start:b_end]
                t_vel_0_b = t_vel_0_t[b_start:b_end]
                t_rcs_b = t_rcs_t[:, b_start:b_end, :]
                
                # Expand positions for this batch at this exact pulse time
                t_pos_curr = t_pos_0_b + t_vel_0_b * t_curr
                
                # --- Dynamic Azimuth Beam Tracking (Stripmap vs Spotlight) ---
                if CFG.get('sar_mode', 'stripmap').lower() == 'spotlight':
                    scene_ct = torch.tensor(CFG.get('scene_center_m', [0.0,0.0,0.0]), device=device, dtype=torch.float64).view(1,3)
                    aim_pt = scene_ct
                else:
                    aim_pt = torch.tensor(CFG.get('scene_center_m', [0.0,0.0,0.0]), device=device, dtype=torch.float64).view(1,3)
                    aim_pt[0, 1] = p_tx[0, 1] # Stripmap sweeps laterally along Y
                    
                dir_base = aim_pt - p_tx
                boresight_vec = dir_base / torch.norm(dir_base)
                forward_vec = v_tx / torch.norm(v_tx)
                
                # Distances to all targets in batch
                tgt_vec = t_pos_curr - p_tx
                dist_tx = torch.norm(tgt_vec, dim=1) 
                dist_rx = torch.norm(t_pos_curr - p_rx, dim=1)
                
                tgt_dir = tgt_vec / dist_tx.view(-1, 1)
                sin_delta_az = torch.sum(tgt_dir * forward_vec, dim=1) - torch.sum(boresight_vec * forward_vec)
                
                G_tx_az_lin = 10**(CFG['antenna_gain_az_dbi'] / 10.0)
                G_el_lin = 10**(CFG['antenna_gain_el_dbi'] / 10.0)
                # Correct 1D array beamwidth mapping (approx 1.772/D)
                az_beamwidth_rad = 1.772 / G_tx_az_lin
                L_az = LAMBDA / az_beamwidth_rad
                psi_az = (np.pi * L_az / LAMBDA) * sin_delta_az
                AF_az = torch.where(torch.abs(psi_az) < 1e-6, torch.ones_like(psi_az), torch.sin(psi_az) / psi_az)
                
                dynamic_gt_lin = G_tx_az_lin * (AF_az**2) * G_el_lin
                
                tau = (dist_tx + dist_rx) / C 
                
                # Mixed-Precision Geometry wrapper
                # strictly bound phase strictly mathematically inside [-pi, pi] under float64 natively
                phase_base_f64 = torch.fmod(-2.0 * np.pi * CFG['center_freq_hz'] * tau, 2.0 * np.pi)
                # extract perfectly bound scalars directly into float32 Native memory
                phase_base_c32 = phase_base_f64.float()
                
                # Expand out parameters across the fast-time sampling grid mapping float32
                tau_grid = tau.view(-1, 1).float()
                t_local = t_fast_t.view(1, -1).float() - tau_grid
                
                mask = torch.abs(t_local - PULSE_WIDTH/2) <= (PULSE_WIDTH/2)
                t_norm = t_local / PULSE_WIDTH
                idx = torch.floor(t_norm * M_res).long()
                idx = torch.clamp(idx, 0, M_res - 1)
                complex_chirp = tx_baseband_t[idx]
                
                # --- Radar Equation for Received Power ---
                # Pr = (Pt * Gt * Gr * lambda^2 * RCS) / ((4*pi)^3 * R_tx^2 * R_rx^2 * L_sys)
                rcs_tensor = t_rcs_b.view(-1, 1)
                
                # --- Dynamic Scan-On-Receive (SCORE) Physics ---
                if CFG['score_mode']:
                    # SCORE Tracks the expected ground return synchronously
                    R_expected = (C * t_local) / 2.0 - CFG['score_scan_ahead_m']
                    
                    # Convert Expected Range to Elevation steering angle (using satellite altitude geometry)
                    # cos(theta_look) = H / R (flat earth approximation relative to satellite)
                    expected_theta_look = torch.acos(torch.clamp(R_sat / R_expected, -1.0, 1.0))
                    
                    # Actual target elevation angle from receiver
                    z_rx_diff = p_rx[0, 2] - t_pos_curr[:, 2] # Up axis difference (Altitude)
                    target_theta_look = torch.acos(torch.clamp(z_rx_diff / dist_rx, -1.0, 1.0))
                    target_theta_look = target_theta_look.view(-1, 1)
                    
                    # Compute Sinc^2 Array Factor Loss (Normalized)
                    # We reverse engineer the synthetic aperture length (L) required for the target `score_rx_gain_el_dbi`
                    # Gain roughly scales as 4*pi*A / lambda^2 -> Let's approximate angular beamwidth: lambda / L
                    score_gain_lin = 10**(CFG['score_rx_gain_el_dbi'] / 10.0)
                    beamwidth_rad = 4.0 * np.pi / score_gain_lin # Rough uniform aperture approximation
                    L_aperture = LAMBDA / beamwidth_rad
                    
                    # Array factor argument: psi = (pi * L / lambda) * (sin(theta_target) - sin(theta_scan))
                    # Simplified to angle difference for localized scanning
                    delta_theta = target_theta_look - expected_theta_look
                    psi = (np.pi * L_aperture / LAMBDA) * torch.sin(delta_theta)
                    
                    # sinc(x) = sin(x)/x, with protection at 0
                    AF = torch.where(torch.abs(psi) < 1e-6, torch.ones_like(psi), torch.sin(psi) / psi)
                    dynamic_gr_lin = score_gain_lin * (AF**2) * (AF_az.view(-1, 1)**2)
                else:
                    dynamic_gr_lin = G_el_lin * G_tx_az_lin * (AF_az.view(-1, 1)**2)
                
                rx_loss_lin = 10**(CFG.get('rx_gain_offset_db', 0.0) / 10.0)
                num_term = CFG['tx_power_w'] * dynamic_gt_lin.view(-1, 1) * dynamic_gr_lin * rx_loss_lin * (LAMBDA**2) * rcs_tensor
                den_term = ((4.0 * np.pi)**3) * (dist_tx.view(-1, 1)**2) * (dist_rx.view(-1, 1)**2) * L_sys_lin
                
                pr_watts = num_term / den_term
                amp = torch.sqrt(pr_watts).float()
                
                # Construct raw target phase shifts at delayed timestamp mapped to complex64
                sig_targets = amp * torch.exp(1j * phase_base_c32.view(-1, 1)) * complex_chirp * mask
                
                # Accumulate this batch's contribution
                pulse_sig += torch.sum(sig_targets, dim=0)
            
        # --- Thermal Noise Injection ---
        # T_sys = T_ant + T0 * (NF_lin - 1)
        # N = k * T_sys * B  (Noise power in Watts over the receiver bandwidth)
        T0 = 290.0
        nf_lin = 10.0**(CFG['noise_figure_db'] / 10.0)
        t_rx = T0 * (nf_lin - 1.0)
        t_sys = CFG['antenna_temp_k'] + t_rx
        noise_power_w = K_B * t_sys * CFG['bandwidth_hz']
        
        # --- Active RF EMI Injection (Time-Domain PRN Synthesis) ---
        if has_emi:
            # 1-Way Path Loss calculates Received Watts
            e_pos_curr = e_pos_t + e_vel_t * t_curr
            dist_rx_emi = torch.norm(e_pos_curr - p_rx, dim=1)
            
            # --- Azimuth Attenuation for EMI ---
            tgt_dir_emi = (e_pos_curr - p_rx) / dist_rx_emi.view(-1, 1)
            sin_delta_az_emi = torch.sum(tgt_dir_emi * forward_vec, dim=1) - torch.sum(boresight_vec * forward_vec)
            G_tx_az_lin = 10**(CFG['antenna_gain_az_dbi'] / 10.0)
            G_el_lin = 10**(CFG['antenna_gain_el_dbi'] / 10.0)
            az_beamwidth_rad = 4.0 * np.pi / G_tx_az_lin
            L_az = LAMBDA / az_beamwidth_rad
            psi_az_emi = (np.pi * L_az / LAMBDA) * sin_delta_az_emi
            AF_az_emi = torch.where(torch.abs(psi_az_emi) < 1e-6, torch.ones_like(psi_az_emi), torch.sin(psi_az_emi) / psi_az_emi)
            
            # --- Dynamic Scan-On-Receive (SCORE) EMI Submersion ---
            # Active sweep across fast-time filters continuous RF emissions 
            if CFG['score_mode']:
                # The sweeping beam expects ranges
                t_global = t_fast_t.view(1, -1)
                R_expected = (C * t_global) / 2.0 - CFG['score_scan_ahead_m']
                expected_theta_look = torch.acos(torch.clamp(R_sat / R_expected, -1.0, 1.0))
                
                # Physical emitter elevation angles
                z_rx_diff_emi = p_rx[0, 2] - e_pos_curr[:, 2]
                emi_theta_look = torch.acos(torch.clamp(z_rx_diff_emi / dist_rx_emi, -1.0, 1.0)).view(-1, 1)
                
                score_gain_lin = 10**(CFG['score_rx_gain_el_dbi'] / 10.0)
                beamwidth_rad = 4.0 * np.pi / score_gain_lin
                L_aperture = LAMBDA / beamwidth_rad
                
                delta_theta = emi_theta_look - expected_theta_look
                psi = (np.pi * L_aperture / LAMBDA) * torch.sin(delta_theta)
                AF = torch.where(torch.abs(psi) < 1e-6, torch.ones_like(psi), torch.sin(psi) / psi)
                
                dynamic_gr_emi_lin = score_gain_lin * (AF**2) * (AF_az_emi.view(-1, 1)**2) # Shape: (num_emitters, num_samples)
            else:
                dynamic_gr_emi_lin = G_el_lin * G_tx_az_lin * (AF_az_emi.view(-1, 1)**2)
            
            # G_rx_lin becomes dynamic across the whole fast-time vector (suppressing off-axis EMI)
            num_term_emi = e_pwr_t.view(-1, 1) * e_gain_t.view(-1, 1) * dynamic_gr_emi_lin * (LAMBDA**2)
            den_term_emi = ((4.0 * np.pi)**2) * (dist_rx_emi.view(-1, 1)**2) * L_sys_lin
            prx_emi_watts = num_term_emi / den_term_emi # Shape: (num_emitters, num_samples)
            
            # Generate random complex frequency bins for all emitters at once
            prn_f = (torch.randn((len(pt_emitters), num_samples), device=device, dtype=torch.float64) + 
                     1j * torch.randn((len(pt_emitters), num_samples), device=device, dtype=torch.float64)) / np.sqrt(2.0)
                     
            # Mask to exact emitter RF bandwidth
            prn_f_masked = prn_f * e_masks_t
            
            # IFFT to orthogonal time-domain complex PRN stream
            prn_t = torch.fft.ifft(torch.fft.ifftshift(prn_f_masked, dim=1), dim=1, norm="ortho")
            
            # Since the IFFT of complex gaussian is scaled to RMS=1 with norm='ortho', 
            # we directly apply the time-varying Watts envelope (SCORE Sweeping effects)
            scale_factors = torch.sqrt(prx_emi_watts) # Shape: (num_emitters, num_samples)
            prn_t_scaled = prn_t * scale_factors
            
            # Doppler phase tracking (maintains realistic phase continuity across slow-time pulses)
            doppler_phase = -2.0 * np.pi * CFG['center_freq_hz'] * (dist_rx_emi / C)
            prn_t_scaled = prn_t_scaled * torch.exp(1j * doppler_phase).view(-1, 1)
            
            # Inject directly into fundamental IQ fast-time stream
            pulse_sig += torch.sum(prn_t_scaled, dim=0)
        
        # Complex noise (circularly symmetric gaussian)
        # Power is divided equally between I and Q channels, so variance per channel is N/2
        noise_std = np.sqrt(noise_power_w / 2.0)
        
        noise_i = torch.randn(num_samples, device=device, dtype=torch.float64) * noise_std
        noise_q = torch.randn(num_samples, device=device, dtype=torch.float64) * noise_std
        complex_noise = torch.complex(noise_i, noise_q)
        
        pulse_sig += complex_noise
        
        # Store accumulated final waveform
        raw_sig[i] = pulse_sig.cpu()
        
    print("\n  Done!")
    return raw_sig.numpy(), t_start_fast, num_samples

# =============================================================================
# 6. MASTER EXECUTION
# =============================================================================
if __name__ == "__main__":
    print("=== Modular SAR Environment ===")
    print(f"O2 Zenith Atten (1-way): {zenith_O2:.4f} dB")
    print(f"H2O Zenith Atten (1-way): {zenith_H2O:.4f} dB")
    print(f"Gaseous Loss (2-way): {loss_gas_db:.2f} dB")
    print(f"Ionospheric Loss (2-way): {loss_iono_db:.4f} dB")
    print(f"Total Atmos/Iono Loss (2-way): {total_atmos_iono_db:.2f} dB")
    
    # 1. Setup Data/Scene
    targets = generate_and_visualize_scene()
    
    # 1b. If OFDM, regenerate waveform with null bands from actual scene emitters
    if CFG['waveform_type'] == 'OFDM':
        generate_ofdm_waveform(targets)
    
    # 2. Setup Timing
    num_pulses = int(np.ceil(CFG['cpi_sec'] * CFG['prf_hz']))
    t_vec = np.arange(num_pulses) / CFG['prf_hz'] - (CFG['cpi_sec'] / 2.0)
    
    # 3. Setup Trajectories
    pos_tx, vel_tx, rx_positions = calculate_trajectories(num_pulses, t_vec)
    
    # 4. Run Physics for all Rx Channels
    rx_channels = []
    t_start_f = 0
    samples = 0
    
    for ch_idx, pos_rx in enumerate(rx_positions):
        print(f"\n--- Channel {ch_idx+1}/{len(rx_positions)} ---")
        raw_rx, t_start_f, samples = simulate_raw_phase_history(targets, t_vec, pos_tx, vel_tx, pos_rx, tx_baseband=tx_baseband)
        rx_channels.append(raw_rx)
        
    # 5. Save Output
    print("\nSaving Raw Multi-Channel Phase History...")
    dest_npz = os.path.join(CFG.get('out_dir', ''), "sar_raw_phase_history.npz") if CFG.get('out_dir', '') else "sar_raw_phase_history.npz"
    np.savez(dest_npz, 
             rx_channels=np.array(rx_channels),
             pos_tx=pos_tx,
             vel_tx=vel_tx,
             pos_rx=np.array(rx_positions),
             sar_mode=CFG.get('sar_mode', 'stripmap'),
             scene_center=CFG.get('scene_center_m', [0.0, 0.0, 0.0]),
             t_start_fast=t_start_f,
             fs=FS,
             prf=CFG['prf_hz'],
             pulse_width=PULSE_WIDTH,
             center_freq=CFG['center_freq_hz'],
             bandwidth=CFG['bandwidth_hz'],
             slow_time=t_vec,
             dpca_active=(str(CFG['rx_spacing_m']).lower() == 'dpca'),
             waveform_type=CFG['waveform_type'],
             tx_baseband=tx_baseband)
    print("Saved to sar_raw_phase_history.npz")
