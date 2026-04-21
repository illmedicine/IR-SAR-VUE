import numpy as np

# --- Frequency-Dependent RCS Scaling ---
# Canonical Frequency Tie-Points (Hz)
RCS_FREQS_HZ = np.array([1.0e9, 3.0e9, 6.0e9, 10.0e9, 15.0e9, 30.0e9]) # L, S, C, X, Ku, Ka

# Scaling factors relative to the standard Base RCS defined in the generators
RCS_PROFILES = {
    'standard':  np.array([1.0, 1.2, 1.5, 2.0, 2.5, 3.0]), # General objects (cars, gen4 jets) get slightly more reflective at higher freqs
    'person':    np.array([1.0, 1.0, 1.1, 1.2, 1.3, 1.5]), # Humans don't scale as dramatically
    'stealth':   np.array([10.0, 5.0, 2.0, 1.0, 2.0, 5.0]), # Stealth Fighter: optimized for X-band (1.0 scale), degrades at L/Ka bands
    'ship':      np.array([1.0, 1.5, 2.0, 3.0, 4.0, 5.0]), # Massive structures become extremely complex/reflective
    'warhead':   np.array([0.8, 1.0, 1.3, 1.5, 1.8, 2.2])  # Metallic conical RV, moderate freq scaling
}

def interpolate_rcs_scale(profile_name, freq_hz):
    """
    Interpolates the RCS scaling factor for a given target profile at a specific frequency.
    """
    if profile_name not in RCS_PROFILES:
        profile_name = 'standard'
    
    scale = np.interp(freq_hz, RCS_FREQS_HZ, RCS_PROFILES[profile_name])
    return scale

def create_point_target(x, y, z, rcs, name=""):
    return {'position': [x, y, z], 'rcs': rcs, 'name': name}

def create_rf_emitter(x, y, z, tx_power_dbm, effective_tx_gain_dbi_to_sat, freq_hz, bandwidth_hz, signal_type, name=""):
    """
    Creates an active RF emitter target metadata.
    Does not have a radar cross section (RCS), but rather emits an active signal.
    """
    return {
        'position': [x, y, z],
        'is_emitter': True,
        'tx_power_dbm': float(tx_power_dbm),
        'effective_tx_gain_dbi_to_sat': float(effective_tx_gain_dbi_to_sat),
        'freq_hz': float(freq_hz),
        'bandwidth_hz': float(bandwidth_hz),
        'signal_type': signal_type,
        'name': name
    }

# --- Existing targets from vehicle_targets.py ---
def generate_car(center_pos=(0,0,0), name_prefix="Car", **kwargs):
    # Dimensions: 4.5m x 1.8m x 1.4m
    # Total RCS goal: ~10 m^2
    targets = []
    cx, cy, cz = center_pos
    
    # Chassis corners
    l, w = 4.5, 1.8
    z_chassis = 0.5
    corners = [
        (l/2, w/2, z_chassis), (l/2, -w/2, z_chassis),
        (-l/2, w/2, z_chassis), (-l/2, -w/2, z_chassis)
    ]
    
    # Roof corners
    l_roof, w_roof = 2.0, 1.4
    z_roof = 1.4
    roof_corners = [
        (l_roof/2, w_roof/2, z_roof), (l_roof/2, -w_roof/2, z_roof),
        (-l_roof/2, w_roof/2, z_roof), (-l_roof/2, -w_roof/2, z_roof)
    ]
    
    # Wheels/Bumpers
    extras = [
        (l/2, 0, 0.4), (-l/2, 0, 0.4) 
    ]
    
    mid_pts = [
        (0, w/2, 0.9), (0, -w/2, 0.9) 
    ]

    scale = interpolate_rcs_scale('standard', kwargs.get('radar_center_freq_hz', 3.0e9))

    for i, (lx, ly, lz) in enumerate(corners + roof_corners + extras + mid_pts):
        r = 1.0 * scale
        targets.append(create_point_target(cx+lx, cy+ly, cz+lz, r, f"{name_prefix}_pt{i}"))
        
    return targets

def generate_tank(center_pos=(0,0,0), name_prefix="Tank"):
    targets = []
    cx, cy, cz = center_pos
    
    l, w, h = 8.0, 3.6, 1.5
    hull_pts = [
        (l/2, w/2, h), (l/2, -w/2, h), (-l/2, w/2, h), (-l/2, -w/2, h),
        (l/2, w/2, 0.5), (l/2, -w/2, 0.5), (-l/2, w/2, 0.5), (-l/2, -w/2, 0.5)
    ]
    
    t_rad = 1.5
    z_turret = 2.3
    turret_pts = [
        (0, 0, z_turret),
        (t_rad, 0, z_turret-0.3), (-t_rad, 0, z_turret-0.3),
        (0, t_rad, z_turret-0.3), (0, -t_rad, z_turret-0.3)
    ]
    
    gun_pts = [
        (l/2 + 1.0, 0, z_turret-0.5), (l/2 + 3.0, 0, z_turret-0.5), (l/2 + 5.0, 0, z_turret-0.5)
    ]
    
    mid_hull_pts = [
        (0, w/2, 1.0), (0, -w/2, 1.0)
    ]
    
    for i, (lx, ly, lz) in enumerate(hull_pts + turret_pts + gun_pts + mid_hull_pts):
        r = 5.0 
        targets.append(create_point_target(cx+lx, cy+ly, cz+lz, r, f"{name_prefix}_pt{i}"))
        
    return targets

def generate_fighter_jet(center_pos=(0,0,0), name_prefix="Jet4Gen", rcs_scale=1.0, **kwargs):
    targets = []
    cx, cy, cz = center_pos
    
    body_pts = [
        (7.5, 0, 0), (5.0, 0, 1.0), (-6.0, 0, 1.0), 
        (-7.0, 0, 0.5), (-6.0, 0, 2.5),
    ]
    
    wing_pts = [
        (0, 2.0, 0), (0, -2.0, 0), (-3.0, 5.0, 0), (-3.0, -5.0, 0),
        (-4.0, 2.5, 0), (-4.0, -2.5, 0)
    ]
    
    stab_pts = [
        (-6.5, 2.0, 0), (-6.5, -2.0, 0)
    ]
    
    scale = interpolate_rcs_scale('standard', kwargs.get('radar_center_freq_hz', 3.0e9))

    for i, (lx, ly, lz) in enumerate(body_pts + wing_pts + stab_pts):
        r = 10.0 * rcs_scale * scale
        targets.append(create_point_target(cx+lx, cy+ly, cz+lz, r, f"{name_prefix}_pt{i}"))

    return targets

def generate_stealth_fighter(center_pos=(0,0,0), name_prefix="StealthJet", **kwargs):
    # Stealth Fighter base RCS is extremely small. The stealth profile will scale it up at off-design frequencies.
    scale = interpolate_rcs_scale('stealth', kwargs.get('radar_center_freq_hz', 10.0e9))
    return generate_fighter_jet(center_pos, name_prefix, rcs_scale=0.001 * scale)

def generate_ballistic_warhead(center_pos=(0,0,0), name_prefix="Warhead", **kwargs):
    """
    Generates a ballistic missile re-entry vehicle (RV) warhead.
    Conical geometry: ~2m long, 0.5m base radius.
    Realistic per-point RCS for a metallic conical body:
      - Nose-on: very small (~0.01 m²)
      - Broadside cone body: ~0.05-0.1 m² per scatter point
      - Base ring: ~0.1-0.2 m² (flat reflector)
    Total composite RCS ~0.5-1.0 m² (consistent with open-source estimates for simple RVs)
    """
    targets = []
    cx, cy, cz = center_pos
    
    scale = interpolate_rcs_scale('warhead', kwargs.get('radar_center_freq_hz', 3.0e9))
    
    # Nose tip (very low RCS - pointed)
    targets.append(create_point_target(cx, cy, cz + 2.0, 0.01 * scale, f"{name_prefix}_nose"))
    
    # Upper cone body ring (4 pts at ~0.5m from tip, r~0.12m)
    for i, angle in enumerate([0, 90, 180, 270]):
        rad = np.radians(angle)
        r = 0.12
        targets.append(create_point_target(
            cx + r * np.cos(rad), cy + r * np.sin(rad), cz + 1.5,
            0.05 * scale, f"{name_prefix}_upper{i}"
        ))
    
    # Mid cone body ring (4 pts at ~1m from tip, r~0.25m)
    for i, angle in enumerate([45, 135, 225, 315]):
        rad = np.radians(angle)
        r = 0.25
        targets.append(create_point_target(
            cx + r * np.cos(rad), cy + r * np.sin(rad), cz + 1.0,
            0.08 * scale, f"{name_prefix}_mid{i}"
        ))
    
    # Base ring (4 pts at base, r~0.5m — flat base is a strong reflector)
    for i, angle in enumerate([0, 90, 180, 270]):
        rad = np.radians(angle)
        r = 0.5
        targets.append(create_point_target(
            cx + r * np.cos(rad), cy + r * np.sin(rad), cz,
            0.15 * scale, f"{name_prefix}_base{i}"
        ))
    
    # Tail flare (ablative heat shield, strong return)
    targets.append(create_point_target(cx, cy, cz - 0.1, 0.2 * scale, f"{name_prefix}_tailflare"))
    
    return targets

def generate_person_only(center_pos=(0,0,0), name_prefix="HumanOnly", **kwargs):
    """
    Generates a person's physical radar scatterers ONLY — no cell phone emitter.
    Used for clean radar-only human detection scenes.
    RCS: ~1.0 m² total (2 scatter points × 0.5 m² each).
    """
    targets = []
    cx, cy, cz = center_pos
    
    scale = interpolate_rcs_scale('person', kwargs.get('radar_center_freq_hz', 3.0e9))
    
    targets.append(create_point_target(cx, cy, cz + 1.0, 0.5 * scale, f"{name_prefix}_torso"))
    targets.append(create_point_target(cx, cy, cz + 0.3, 0.5 * scale, f"{name_prefix}_legs"))
    
    return targets

# In-band emitter bands that overlap the radar's 1750-2250 MHz passband
INBAND_EMITTER_BANDS = [
    # PCS Uplink (UE transmitting to tower)
    {'name': 'PCS_UL_B2', 'freq_range_mhz': (1850, 1915), 'bw_mhz': [5, 10, 15, 20], 'type': '5G_PRN',
     'tx_power_dbm_range': (15.0, 23.0), 'gain_type': 'ue'},
    # PCS Downlink (Tower transmitting to UE)
    {'name': 'PCS_DL_B2', 'freq_range_mhz': (1930, 1995), 'bw_mhz': [5, 10, 15, 20], 'type': '5G_PRN',
     'tx_power_dbm_range': (40.0, 47.0), 'gain_type': 'tower'},
    # AWS Uplink
    {'name': 'AWS_UL_B66', 'freq_range_mhz': (1710, 1780), 'bw_mhz': [5, 10, 15, 20], 'type': '5G_PRN',
     'tx_power_dbm_range': (15.0, 23.0), 'gain_type': 'ue'},
    # AWS Downlink
    {'name': 'AWS_DL_B66', 'freq_range_mhz': (2110, 2200), 'bw_mhz': [5, 10, 15, 20], 'type': '5G_PRN',
     'tx_power_dbm_range': (40.0, 47.0), 'gain_type': 'tower'},
]

def generate_inband_emitter(center_pos=(0,0,0), name_prefix="InBandEMI", satellite_grazing_angle_deg=45.0, rng=None, **kwargs):
    """
    Generates an RF emitter specifically in the radar's S-band passband (1750-2250 MHz).
    These are real PCS and AWS cellular signals that directly overlap with 2 GHz SAR.
    """
    if rng is None:
        rng = np.random.default_rng()
    
    targets = []
    cx, cy, cz = center_pos
    
    # Filter bands to only include 'ue' (Cell Phones) to bypass tower sky-gain nulls
    ue_bands = [b for b in INBAND_EMITTER_BANDS if b['gain_type'] == 'ue']
    band = rng.choice(ue_bands)
    
    # Pick a valid channel
    bw_mhz = rng.choice(band['bw_mhz'])
    # Allow deterministic override of CF, BW, and TX Power
    bw_hz = kwargs.get('bandwidth_hz_override', bw_mhz * 1e6)
    
    if kwargs.get('center_freq_hz_override') is not None:
        cf_hz = kwargs.get('center_freq_hz_override')
    else:
        freq_min = band['freq_range_mhz'][0] * 1e6 + bw_hz / 2
        freq_max = band['freq_range_mhz'][1] * 1e6 - bw_hz / 2
        if freq_max < freq_min:
            cf_hz = (band['freq_range_mhz'][0] + band['freq_range_mhz'][1]) * 1e6 / 2
        else:
            cf_hz = rng.uniform(freq_min, freq_max)
    
    tx_power_dbm = kwargs.get('tx_power_dbm_override', rng.uniform(*band['tx_power_dbm_range']))
    
    if band['gain_type'] == 'tower':
        peak_gain = rng.uniform(15.0, 25.0)
        eff_gain = calc_tower_sky_gain(satellite_grazing_angle_deg, peak_gain, rng)
        z_height = rng.uniform(15.0, 40.0)
    else:
        eff_gain = calc_ue_sky_gain(satellite_grazing_angle_deg, rng)
        z_height = 1.2
    
    targets.append(create_rf_emitter(
        cx, cy, cz + z_height,
        tx_power_dbm, eff_gain,
        cf_hz, bw_hz, band['type'],
        f"{name_prefix}_{band['name']}_{int(cf_hz/1e6)}MHz"
    ))
    
    return targets

def generate_destroyer(center_pos=(0,0,0), name_prefix="Destroyer"):
    # Arleigh Burke Flight I approx: 154m x 20m
    # Total RCS goal: ~50,000 m^2 (Typical large ship)
    targets = []
    cx, cy, cz = center_pos
    
    length = 154.0
    width = 20.0
    
    # Grid of points along the hull - REVERTED TO LOW RES
    rows = 5
    cols = 3 
    
    x_steps = np.linspace(-length/2, length/2, rows)
    y_steps = np.linspace(-width/2, width/2, cols)
    
    # Hull points (15 * 2 = 30 points)
    for x in x_steps:
        for y in y_steps:
            # Hull and Deck - massive vertical surfaces
            targets.append(create_point_target(cx+x, cy+y, cz+1, 1000.0, f"{name_prefix}_hull"))
            targets.append(create_point_target(cx+x, cy+y, cz+6, 1000.0, f"{name_prefix}_deck"))
            
    # Superstructure (strong corner reflectors)
    bridge_x = length * 0.2
    targets.append(create_point_target(cx+bridge_x, cy, cz+15, 5000.0, f"{name_prefix}_bridge"))
    
    mast_x = length * 0.1
    targets.append(create_point_target(cx+mast_x, cy, cz+25, 3000.0, f"{name_prefix}_mast"))
    
    stack_x = -length * 0.1
    targets.append(create_point_target(cx+stack_x, cy, cz+12, 3000.0, f"{name_prefix}_stack"))
    
    bow_x = length/2.0 + 10.0
    targets.append(create_point_target(cx+bow_x, cy, cz+6, 1000.0, f"{name_prefix}_bow"))
    
    stern_x = -length/2.0 - 5.0
    targets.append(create_point_target(cx+stern_x, cy, cz+6, 1000.0, f"{name_prefix}_stern"))
    
    return targets

# --- Comprehensive US Cellular Bands Database ---
# Format: Band Name, Uplink Range (MHz), Downlink Range (MHz), Typical Bandwidths (MHz), Type
CELL_BANDS = [
    # Low Band (Long range, typically FDD)
    {'name': 'B71/n71 (600MHz)', 'ul_mhz': (663, 698), 'dl_mhz': (617, 652), 'bw_mhz': [5, 10, 15, 20], 'type': '5G_PRN'},
    {'name': 'B12/B17 (700MHz)', 'ul_mhz': (698, 716), 'dl_mhz': (728, 746), 'bw_mhz': [5, 10], 'type': '4G_PRN'},
    {'name': 'B13 (700MHz Upper)', 'ul_mhz': (776, 787), 'dl_mhz': (746, 756), 'bw_mhz': [5, 10], 'type': '4G_PRN'},
    {'name': 'B14 (700MHz FirstNet)', 'ul_mhz': (788, 798), 'dl_mhz': (758, 768), 'bw_mhz': [5, 10], 'type': '4G_PRN'},
    {'name': 'B5/n5 (850MHz)', 'ul_mhz': (824, 849), 'dl_mhz': (869, 894), 'bw_mhz': [5, 10, 15, 20], 'type': '5G_PRN'},
    
    # Mid Band - FDD (Separate UL/DL)
    {'name': 'B4/B66/n66 (AWS)', 'ul_mhz': (1710, 1780), 'dl_mhz': (2110, 2200), 'bw_mhz': [5, 10, 15, 20], 'type': '5G_PRN'},
    {'name': 'B2/B25/n2 (PCS)', 'ul_mhz': (1850, 1915), 'dl_mhz': (1930, 1995), 'bw_mhz': [5, 10, 15, 20], 'type': '5G_PRN'},
    {'name': 'B30 (WCS)', 'ul_mhz': (2305, 2315), 'dl_mhz': (2350, 2360), 'bw_mhz': [5, 10], 'type': '4G_PRN'},
    
    # Mid Band - TDD (Shared UL/DL Time Division)
    {'name': 'B41/n41 (2.5GHz)', 'ul_mhz': (2496, 2690), 'dl_mhz': (2496, 2690), 'bw_mhz': [20, 40, 60, 80, 100], 'type': '5G_PRN'},
    {'name': 'B48 (CBRS)', 'ul_mhz': (3550, 3700), 'dl_mhz': (3550, 3700), 'bw_mhz': [10, 20, 40], 'type': '4G_PRN'},
    {'name': 'n77 (C-Band)', 'ul_mhz': (3700, 3980), 'dl_mhz': (3700, 3980), 'bw_mhz': [20, 40, 60, 80, 100], 'type': '5G_PRN'},
    
    # High Band / mmWave (TDD)
    {'name': 'n261 (28GHz)', 'ul_mhz': (27500, 28350), 'dl_mhz': (27500, 28350), 'bw_mhz': [50, 100, 200, 400], 'type': '5G_PRN'},
    {'name': 'n260 (39GHz)', 'ul_mhz': (37000, 40000), 'dl_mhz': (37000, 40000), 'bw_mhz': [50, 100, 200, 400], 'type': '5G_PRN'}
]

def generate_random_emission_from_band(band, is_uplink, rng):
    """
    Given a band definition, randomly select a valid channel bandwidth and a 
    center frequency that fits entirely within the UL or DL allocation.
    """
    bw_mhz = rng.choice(band['bw_mhz'])
    bw_hz = bw_mhz * 1e6
    
    freq_range = band['ul_mhz'] if is_uplink else band['dl_mhz']
    min_freq_hz = freq_range[0] * 1e6 + (bw_hz / 2.0)
    max_freq_hz = freq_range[1] * 1e6 - (bw_hz / 2.0)
    
    # If the bandwidth is larger than the allocation (rare edge case), center it
    if max_freq_hz < min_freq_hz:
        cf_hz = (freq_range[0] * 1e6 + freq_range[1] * 1e6) / 2.0
    else:
        cf_hz = rng.uniform(min_freq_hz, max_freq_hz)
        
    return cf_hz, bw_hz

def calc_tower_sky_gain(gamma_deg, peak_gain_dbi, rng):
    """
    Simulates the exact effective gain of a downtilted sector antenna towards the sky
    using a Uniform Linear Array (ULA) mathematical model.
    """
    # 1. Physical Antenna Properties
    num_elements = 8            # Standard macro cell vertical array size
    tilt_deg = rng.uniform(2.0, 12.0) # Random electrical/mechanical downtilt
    
    # Convert to radians
    theta_rad = np.radians(gamma_deg) 
    tilt_rad = np.radians(-tilt_deg)  # Pointing below horizon
    
    # 2. Calculate Array Factor (AF) Phase Difference
    # phi = (2 * pi * d / lambda) * (sin(theta) - sin(theta_0)) 
    # Assumes half-wavelength spacing (d = 0.5 * lambda) so (2 * pi * 0.5) = pi
    psi = np.pi * (np.sin(theta_rad) - np.sin(tilt_rad))
    
    # 3. Calculate AF Magnitude
    # |AF| = | sin(N * psi / 2) / (N * sin(psi / 2)) |
    # Handle division by zero at boresight
    if np.abs(psi) < 1e-9:
        af_linear = 1.0
    else:
        af_linear = np.abs(np.sin(num_elements * psi / 2.0) / (num_elements * np.sin(psi / 2.0)))
        
    af_db = 20.0 * np.log10(max(af_linear, 1e-4)) # Lower bound to prevent log(0)
    
    # 4. Element Factor (EF)
    # The individual dipoles aren't perfectly isotropic. 
    # Standard approximation is cos(theta)^2 or similar.
    ef_db = 10.0 * np.log10(np.cos(theta_rad)**2 + 0.01) # 0.01 prevents -inf at exactly 90 deg
    
    # 5. Total Effective Gain
    # Assumes peak_gain_dbi is achieved at boresight (af_db = 0, ef_db = 0)
    total_gain_dbi = peak_gain_dbi + af_db + ef_db
    
    return total_gain_dbi

def calc_dipole_sky_gain(gamma_deg, peak_gain_dbi):
    """
    Simulates a standard vertical dipole donut pattern.
    Gain drops as cos^2(gamma) as it approaches zenith.
    """
    gamma_rad = np.radians(gamma_deg)
    linear_peak = 10.0 ** (peak_gain_dbi / 10.0)
    linear_eff = linear_peak * (np.cos(gamma_rad)**2) + 0.01
    return 10.0 * np.log10(linear_eff)

def calc_ue_sky_gain(gamma_deg, rng):
    """
    Simulates a cell phone's gain towards the sky.
    Omnidirectional but subject to body blocking and multipath fading.
    """
    # Base gain ~0 dBi. Let's add multipath fading N(0, 3)
    base_gain = rng.normal(0.0, 3.0)
    # Slight penalty for extremely high angles if held vertically
    if gamma_deg > 60.0:
        base_gain -= 3.0
    return base_gain

# --- New City Targets ---
def generate_person(center_pos=(0,0,0), name_prefix="Person", satellite_grazing_angle_deg=45.0, rng=None, **kwargs):
    """
    Generates a person with a standard RCS (two main scatterers) 
    and a cell phone emitting 4G/5G signals on an Uplink frequency.
    """
    if rng is None:
        rng = np.random.default_rng()
        
    targets = []
    cx, cy, cz = center_pos
    
    scale = interpolate_rcs_scale('person', kwargs.get('radar_center_freq_hz', 3.0e9))

    # 1. Physical Radar Cross Section (RCS) of a human
    targets.append(create_point_target(cx, cy, cz + 1.0, 0.5 * scale, f"{name_prefix}_torso"))
    targets.append(create_point_target(cx, cy, cz + 0.3, 0.5 * scale, f"{name_prefix}_legs"))
    
    # 2. Cell Phone Active Emission (UE - Uplink)
    band = rng.choice(CELL_BANDS)
    cf_hz, bw_hz = generate_random_emission_from_band(band, is_uplink=True, rng=rng)
    
    # Typical UE power: ~23 dBm (200mW) for sub-6GHz. 
    if 'GHz' in band['name'] and ('28' in band['name'] or '39' in band['name']):
        tx_power_dbm = rng.uniform(20.0, 26.0) # Up to Class 2 for mmWave
    else:
        tx_power_dbm = rng.uniform(15.0, 23.0) # Typical power control range
        
    eff_gain_dbi = calc_ue_sky_gain(satellite_grazing_angle_deg, rng)
        
    targets.append(create_rf_emitter(
        cx, cy, cz + 1.2, # Phone held at chest/head height
        tx_power_dbm, eff_gain_dbi, 
        cf_hz, bw_hz, band['type'], 
        f"{name_prefix}_Phone_{band['name'].split(' ')[0]}"
    ))
    
    return targets

def generate_cell_tower(center_pos=(0,0,0), name_prefix="Tower", satellite_grazing_angle_deg=45.0, rng=None, **kwargs):
    """
    Generates a Cellular Base Station (eNodeB/gNodeB) structure and strong Downlink emissions.
    These are major sources of interference in the 600MHz - 40GHz bands.
    """
    if rng is None:
        rng = np.random.default_rng()
        
    targets = []
    cx, cy, cz = center_pos
    
    scale = interpolate_rcs_scale('standard', kwargs.get('radar_center_freq_hz', 3.0e9))

    # Physical structure: Massive metallic tower/monopole + antennas
    # Modeled as a few strong points
    height = rng.uniform(15.0, 40.0) # 15m to 40m tall
    targets.append(create_point_target(cx, cy, cz + height/2.0, 10.0 * scale, f"{name_prefix}_mast"))
    targets.append(create_point_target(cx, cy, cz + height, 20.0 * scale, f"{name_prefix}_array"))
    
    # 2. Cell Tower Active Emission (Base Station - Downlink)
    # Towers often transmit on multiple bands, but we will pick 1-3 random bands per tower
    num_carriers = rng.integers(1, 4)
    selected_bands = rng.choice(CELL_BANDS, num_carriers, replace=False)
    
    for i, band in enumerate(selected_bands):
        cf_hz, bw_hz = generate_random_emission_from_band(band, is_uplink=False, rng=rng)
        
        # Base Station Power: Highly powerful. 40-50 dBm (10W - 100W) per sector per carrier
        tx_power_dbm = rng.uniform(40.0, 50.0)
        
        # Base Station Gain: Sector antennas are highly directional
        # Array gain from 15 dBi to 25 dBi
        peak_gain_dbi = rng.uniform(15.0, 25.0)
        eff_gain_dbi = calc_tower_sky_gain(satellite_grazing_angle_deg, peak_gain_dbi, rng)
        
        targets.append(create_rf_emitter(
            cx, cy, cz + height, # Emitting from top of the tower
            tx_power_dbm, eff_gain_dbi, 
            cf_hz, bw_hz, band['type'], 
            f"{name_prefix}_Carrier{i}_{band['name'].split(' ')[0]}"
        ))
        
    return targets

def generate_wifi_router(center_pos=(0,0,0), name_prefix="WiFi", satellite_grazing_angle_deg=45.0, rng=None, **kwargs):
    """
    Generates a stationary WiFi router / access point, common in urban environments.
    """
    if rng is None:
        rng = np.random.default_rng()
        
    targets = []
    cx, cy, cz = center_pos
    
    scale = interpolate_rcs_scale('standard', kwargs.get('radar_center_freq_hz', 3.0e9))

    # Physical scatterer (metallic/plastic box on a pole or wall)
    targets.append(create_point_target(cx, cy, cz, 2.0 * scale, f"{name_prefix}_Box"))
    
    # WiFi emission characteristics
    # Typically 2.4 GHz or 5.8 GHz, 20 MHz to 80 MHz bandwidth
    bands = [
        {'freq_hz': 2.412e9, 'bw_hz': 20e6}, # Channel 1
        {'freq_hz': 2.437e9, 'bw_hz': 20e6}, # Channel 6
        {'freq_hz': 2.462e9, 'bw_hz': 20e6}, # Channel 11
        {'freq_hz': 5.745e9, 'bw_hz': 80e6}, # UNII-3
        {'freq_hz': 5.180e9, 'bw_hz': 40e6}  # UNII-1
    ]
    band = rng.choice(bands)
    
    band_mhz = int(band['freq_hz'] / 1e6)
    
    peak_gain_dbi = rng.uniform(3.0, 6.0) # Directional/Omni
    eff_gain_dbi = calc_dipole_sky_gain(satellite_grazing_angle_deg, peak_gain_dbi)
    
    targets.append(create_rf_emitter(
        cx, cy, cz,
        tx_power_dbm=rng.uniform(20.0, 30.0),   # 100 mW to 1 W
        effective_tx_gain_dbi_to_sat=eff_gain_dbi,
        freq_hz=band['freq_hz'],
        bandwidth_hz=band['bw_hz'],
        signal_type='WiFi_PRN',
        name=f"{name_prefix}_AP_{band_mhz}MHz"
    ))
    
    return targets

def generate_city_scene(seed=42, num_people=50, num_wifi=10, num_cars=20, num_towers=2, area_size=(1000, 1000), satellite_grazing_angle_deg=45.0, radar_center_freq_hz=3.0e9):
    """
    Procedurally generates a city scene with people (and cell phones), WiFi routers, cell towers, and cars.
    
    Parameters:
      seed: Random seed for procedural generation.
      num_people: Number of pedestrians (each with a cell phone).
      num_wifi: Number of stationary WiFi emitters.
      num_cars: Number of cars.
      num_towers: Number of Cellular Base Stations.
      area_size: Tuple of (x_size, y_size) in meters for the bounding box.
      satellite_grazing_angle_deg: Elevation angle of the receiving satellite, used for effective gain.
      radar_center_freq_hz: Frequency used to dynamically scale Radar Cross Section logic.
      
    Returns list of dicts representing point targets and RF emitters.
    """
    rng = np.random.default_rng(seed)
    all_targets = []
    
    def place_rotated_moving_objects(generator_func, num_objects, name_base, speed_range, z_offset=0.0):
        for i in range(num_objects):
            cx = rng.uniform(-area_size[0]/2, area_size[0]/2)
            cy = rng.uniform(-area_size[1]/2, area_size[1]/2)
            
            speed = rng.uniform(speed_range[0], speed_range[1])
            heading = rng.uniform(0, 2 * np.pi)
            vx = speed * np.cos(heading)
            vy = speed * np.sin(heading)
            
            # Generate at origin to rotate easily
            targets = generator_func(center_pos=(0, 0, 0), name_prefix=f"{name_base}_{i}", 
                                     satellite_grazing_angle_deg=satellite_grazing_angle_deg, 
                                     rng=rng, radar_center_freq_hz=radar_center_freq_hz)
            
            cos_h = np.cos(heading)
            sin_h = np.sin(heading)
            
            for t in targets:
                x0, y0, z0 = t['position']
                x_rot = x0 * cos_h - y0 * sin_h
                y_rot = x0 * sin_h + y0 * cos_h
                t['position'] = [x_rot + cx, y_rot + cy, z0 + z_offset]
                t['velocity'] = [float(vx), float(vy), 0.0]
                t['group_id'] = f"{name_base}_{i}"
                
            all_targets.extend(targets)

    # Cars (10 to 25 m/s)
    place_rotated_moving_objects(generate_car, num_cars, "Car", (10.0, 25.0))
    
    # People (1.0 to 1.8 m/s)
    place_rotated_moving_objects(generate_person, num_people, "Person", (1.0, 1.8))
    
    # Generate WiFi Routers (Stationary)
    for i in range(num_wifi):
        cx = rng.uniform(-area_size[0]/2, area_size[0]/2)
        cy = rng.uniform(-area_size[1]/2, area_size[1]/2)
        cz = rng.uniform(3.0, 5.0)
        all_targets.extend(generate_wifi_router((cx, cy, cz), name_prefix=f"WiFi_{i}", satellite_grazing_angle_deg=satellite_grazing_angle_deg, rng=rng, radar_center_freq_hz=radar_center_freq_hz))
        
    # Generate Cell Towers (Stationary)
    for i in range(num_towers):
        cx = rng.uniform(-area_size[0]/2, area_size[0]/2)
        cy = rng.uniform(-area_size[1]/2, area_size[1]/2)
        all_targets.extend(generate_cell_tower((cx, cy, 0), name_prefix=f"Tower_{i}", satellite_grazing_angle_deg=satellite_grazing_angle_deg, rng=rng, radar_center_freq_hz=radar_center_freq_hz))
        
    return all_targets
