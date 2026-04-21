import os
import re

with open('sar_simulation_env.py', 'r', encoding='utf-8') as f:
    code = f.read()

# Modify CFG dictionary
code = re.sub(
    r"'tx_enabled': True,", 
    r"'tx_enabled': False,\n    'out_dir': 'SIGINT Sim Results',", 
    code
)
code = re.sub(
    r"'num_rx_antennas': 1,", 
    r"'num_rx_antennas': 4,", 
    code
)
code = re.sub(
    r"'rx_spacing_m': 'dpca',", 
    r"'rx_spacing_m': [[3.0, 3.0, 0.0], [3.0, -3.0, 0.0], [-3.0, 3.0, 0.0], [-3.0, -3.0, 0.0]],", 
    code
)
code = re.sub(
    r"'is_bistatic': False,", 
    r"'is_bistatic': True,", 
    code
)

# Insert num_inband_emitters override before they are added
code = code.replace(
    "num_inband = CFG.get('num_inband_emitters', 0)",
    "num_inband = CFG.get('num_inband_emitters', 200) # Increased density for SIGINT"
)

# Overwrite calculate_trajectories spacing parsing
rx_calc_orig = """            if isinstance(spacing_val, list):
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
            rx_positions.append(pos_rx)"""

rx_calc_new = """            if isinstance(spacing_val, list):
                if isinstance(spacing_val[rx_idx], list):
                    offset_along = float(spacing_val[rx_idx][0])
                    offset_cross = float(spacing_val[rx_idx][1])
                    offset_radial = float(spacing_val[rx_idx][2])
                else:
                    offset_along = float(spacing_val[rx_idx]) if rx_idx < len(spacing_val) else 0.0
                    offset_cross = 0.0
                    offset_radial = 0.0
            else:
                offset_along = (rx_idx - (CFG['num_rx_antennas'] - 1) / 2.0) * float(spacing_val)
                offset_cross = 0.0
                offset_radial = 0.0
                
            pos_rx = np.copy(pos_tx)
            for i in range(num_pulses):
                v_dir = vel_tx[i] / np.linalg.norm(vel_tx[i])
                radial_dir = pos_tx[i] / np.linalg.norm(pos_tx[i])
                cross_dir = np.cross(v_dir, radial_dir)
                cross_dir = cross_dir / np.linalg.norm(cross_dir)
                
                pos_rx[i] = pos_tx[i] + v_dir * offset_along + cross_dir * offset_cross + radial_dir * offset_radial
            rx_positions.append(pos_rx)"""

code = code.replace(rx_calc_orig, rx_calc_new)

if not os.path.exists("SIGINT Sim Results"):
    os.makedirs("SIGINT Sim Results")

with open('sigint_sim_env.py', 'w', encoding='utf-8') as f:
    f.write(code)

print("sigint_sim_env.py generated successfully.")
