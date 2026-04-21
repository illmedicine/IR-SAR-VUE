import json
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.lines import Line2D
import numpy as np
import math

def load_simulation_data(filepath='city_simulation.json'):
    with open(filepath, 'r') as f:
        data = json.load(f)
    return data['config'], data['timeline']

def extract_target_paths(timeline):
    """ Extracts the (x,y) path history for all non-clutter objects """
    paths = {}
    for frame_idx, frame in enumerate(timeline):
        for t in frame:
            if t.get('type') == 'clutter':
                continue
            
            group_id = t.get('group_id', t['name'])
            if group_id not in paths:
                paths[group_id] = {'x': [], 'y': []}
            
            paths[group_id]['x'].append(t['position'][0])
            paths[group_id]['y'].append(t['position'][1])
            
    return paths

def format_band(freq_hz, bw_hz):
    min_f = freq_hz - bw_hz / 2.0
    max_f = freq_hz + bw_hz / 2.0
    if min_f >= 1e9:
        return f"{min_f/1e9:.2f}-{max_f/1e9:.2f} GHz"
    else:
        return f"{min_f/1e6:.0f}-{max_f/1e6:.0f} MHz"

def render_city_view(config, timeline, output_filename='city_view.png'):
    print("Rendering City View...")
    
    # We will visualize the first frame (start of CPI) with trails showing where they go
    render_frame = timeline[0]
    
    fig, ax = plt.subplots(figsize=(14, 14))
    
    # Set plot limits
    half_w = config['area_size'][0] / 2
    half_h = config['area_size'][1] / 2
    ax.set_xlim(-half_w, half_w)
    ax.set_ylim(-half_h, half_h)
    
    ax.set_title("Radar City Simulator - Final State", fontsize=16)
    ax.set_xlabel("East (m)")
    ax.set_ylabel("North (m)")
    ax.grid(True, linestyle='--', alpha=0.5)
    ax.set_facecolor('#f0f4f8')
    
    # 1. Plot Paths
    paths = extract_target_paths(timeline)
    for group_id, path in paths.items():
        if len(path['x']) > 1:
            line_color = 'gray'
            if 'Car' in group_id: line_color = 'blue'
            elif 'Person' in group_id: line_color = 'green'
            elif 'Jet' in group_id: line_color = 'purple'
            elif 'StealthJet' in group_id: line_color = 'black'
            ax.plot(path['x'], path['y'], color=line_color, linestyle='-', linewidth=1.5, alpha=0.5)
    
    # Render grouping logic to avoid scattering labels for multi-point targets like Jets/Cars
    drawn_groups = set()
    
    # 2. Render points
    for t in render_frame:
        x, y, z = t['position']
        name = t['name']
        
        # A. Clutter
        if t.get('type') == 'clutter':
            # Map RCS to alpha/size
            rcs = t['rcs']
            alpha = min(max(rcs / 100.0, 0.05), 0.5) # Cap transparency
            size = min(max(rcs, 5), 50)
            ax.scatter(x, y, s=size, c='gray', alpha=alpha, marker='.')
            continue
            
        group_id = t.get('group_id', name)
        
        # B. Emitters (Cell Towers, WiFi, Phones)
        if t.get('is_emitter', False):
            if 'Tower' in name:
                marker, color, size = '^', 'red', 80
                label_color = 'darkred'
                offset_y = -8
            elif 'WiFi' in name:
                marker, color, size = 's', 'cyan', 40
                label_color = 'teal'
                offset_y = -8
            elif 'Phone' in name:
                marker, color, size = 'p', 'green', 25
                label_color = 'darkgreen'
                offset_y = 8
            else:
                marker, color, size = '*', 'orange', 30
                label_color = 'orange'
                offset_y = -8
                
            ax.scatter(x, y, s=size, c=color, marker=marker, edgecolors='black', zorder=5)
            
            # Annotate emitting properties
            band_str = format_band(t['freq_hz'], t['bandwidth_hz'])
            pwr_str = f"{t['tx_power_dbm']:.0f}dBm"
            ax.text(x, y + offset_y, f"{band_str}\n{pwr_str}", 
                    color=label_color, fontsize=7, ha='center', va='center',
                    bbox=dict(facecolor='white', alpha=0.7, edgecolor='none', pad=1))
            
        # C. Physical Targets (Cars, People, Jets)
        else:
            if 'Car' in name:
                marker, color, size = 's', 'blue', 15
            elif 'Person' in name:
                marker, color, size = 'o', 'green', 10
            elif 'Jet' in name or 'StealthJet' in name:
                marker, color, size = '*', ('black' if 'StealthJet' in name else 'purple'), 80
            elif 'Tower' in name or 'mast' in name or 'array' in name:
                marker, color, size = '^', 'darkred', 20 # Base structure
            elif 'WiFi' in name and 'Box' in name:
                marker, color, size = 's', 'darkcyan', 15
            else:
                marker, color, size = 'o', 'gray', 10
                
            ax.scatter(x, y, s=size, c=color, marker=marker, edgecolors='none' if 'Person' in name else 'white', zorder=4)

        # D. Group Annotations (Jet Altitudes, Car/Person Speeds)
        if group_id not in drawn_groups:
            drawn_groups.add(group_id)
            if 'Jet' in group_id or 'StealthJet' in group_id:
                vx, vy, vz = t['velocity']
                speed = math.hypot(vx, vy)
                ax.text(x, y - 25, f"Alt: {z:.0f}m\nv: {speed:.0f}m/s", 
                        color='black', fontsize=9, ha='center', va='top', fontweight='bold',
                        bbox=dict(facecolor='white', alpha=0.8, edgecolor='black', boxstyle='round,pad=0.3'))
            elif 'Car' in group_id or 'Person' in group_id:
                vx, vy, vz = t['velocity']
                speed = math.hypot(vx, vy)
                ax.text(x, y - 10, f"v: {speed:.1f}m/s", 
                        color='black', fontsize=7, ha='center', va='top',
                        bbox=dict(facecolor='white', alpha=0.6, edgecolor='none', pad=0.5))
                
    # Legened setup
    legend_elements = [
        Line2D([0], [0], marker='.', color='w', markerfacecolor='gray', markersize=10, label='Suburban Clutter'),
        Line2D([0], [0], marker='s', color='w', markerfacecolor='blue', markersize=10, label='Car (Moving)'),
        Line2D([0], [0], marker='o', color='w', markerfacecolor='green', markersize=8, label='Person (Moving)'),
        Line2D([0], [0], marker='p', color='w', markerfacecolor='green', markeredgecolor='black', markersize=10, label='Cell Phone (Tx)'),
        Line2D([0], [0], marker='s', color='w', markerfacecolor='cyan', markeredgecolor='black', markersize=10, label='WiFi AP (Tx)'),
        Line2D([0], [0], marker='^', color='w', markerfacecolor='red', markeredgecolor='black', markersize=15, label='Cell Tower (Tx)'),
        Line2D([0], [0], marker='*', color='w', markerfacecolor='purple', markeredgecolor='white', markersize=15, label='Fighter Jet'),
        Line2D([0], [0], marker='*', color='w', markerfacecolor='black', markeredgecolor='white', markersize=15, label='Stealth Jet')
    ]
    ax.legend(handles=legend_elements, loc='upper right', framealpha=0.9, title="Radar Targets & Emitters")
    
    plt.tight_layout()
    plt.savefig(output_filename, dpi=300, bbox_inches='tight')
    print(f"Saved visualization to {output_filename}")

if __name__ == "__main__":
    try:
        cfg, tl = load_simulation_data()
        render_city_view(cfg, tl)
    except FileNotFoundError:
        print("city_simulation.json not found! Please run generate_city.py first.")
