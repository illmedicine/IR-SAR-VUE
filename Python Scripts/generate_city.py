import numpy as np
import json
import math
from city_targets import generate_person, generate_wifi_router, generate_cell_tower, generate_car, generate_fighter_jet, generate_stealth_fighter, interpolate_rcs_scale

def check_collision(pos, existing_positions, min_dist):
    """
    Checks if a given position is too close to any existing positions.
    Assumes 2D collision check on the ground (x, y).
    """
    for ex_pos in existing_positions:
        dist = math.hypot(pos[0] - ex_pos[0], pos[1] - ex_pos[1])
        if dist < min_dist:
            return True
    return False

def generate_distributed_clutter(rng, area_size, num_clutter_pts, target_total_rcs):
    """
    Scatters deterministic clutter points whose sum equals the expected environmental RCS.
    Uses an exponential distribution for realistic variance (Rayleigh scattered amplitude).
    """
    clutter = []
    
    # Expected mean RCS per scatterer
    mean_rcs = target_total_rcs / num_clutter_pts
    
    # Generate exponentially distributed RCS values
    rcs_values = rng.exponential(scale=mean_rcs, size=num_clutter_pts)
    
    # Normalize to exactly match the target sum
    rcs_values *= (target_total_rcs / np.sum(rcs_values))
    
    for i in range(num_clutter_pts):
        cx = rng.uniform(-area_size[0]/2, area_size[0]/2)
        cy = rng.uniform(-area_size[1]/2, area_size[1]/2)
        clutter.append({
            'name': f'Clutter_{i}',
            'position': [float(cx), float(cy), 0.0],
            'rcs': float(rcs_values[i]),
            'velocity': [0.0, 0.0, 0.0],
            'type': 'clutter'
        })
        
    return clutter

def initialize_scene(rng, config):
    """
    Initializes all targets, their initial positions, and assigns velocities.
    """
    area_size = config['area_size']
    sat_angle = config['satellite_grazing_angle_deg']
    center_freq = config.get('radar_center_freq_hz', 3.0e9)
    
    objects = []
    occupied_positions = []
    
    def try_place_object(name_prefix, generator_func, min_dist, is_moving=False, speed_range=(0,0), z_offset=0.0, custom_args=None):
        if custom_args is None:
            custom_args = {}
            
        placed = False
        attempts = 0
        while not placed and attempts < 100:
            cx = rng.uniform(-area_size[0]/2, area_size[0]/2)
            cy = rng.uniform(-area_size[1]/2, area_size[1]/2)
            cz = z_offset
            
            if not check_collision((cx, cy), occupied_positions, min_dist):
                occupied_positions.append((cx, cy))
                
                # Assign velocity and heading
                vx, vy, vz = 0.0, 0.0, 0.0
                heading = 0.0
                if is_moving:
                    speed = rng.uniform(speed_range[0], speed_range[1])
                    heading = rng.uniform(0, 2 * math.pi)
                    vx = speed * math.cos(heading)
                    vy = speed * math.sin(heading)
                
                # Generate the specific targets (dots/emitters) for this object at origin (0,0,0) first
                # so we can cleanly rotate them before moving to (cx, cy, cz)
                obj_targets = generator_func(center_pos=(0, 0, 0), name_prefix=name_prefix, **custom_args)
                
                cos_h = math.cos(heading)
                sin_h = math.sin(heading)
                
                # Rotate and translate all components, add group ID and velocity
                for t in obj_targets:
                    x0, y0, z0 = t['position']
                    
                    # 2D Z-axis rotation
                    x_rot = x0 * cos_h - y0 * sin_h
                    y_rot = x0 * sin_h + y0 * cos_h
                    
                    # Translate to final position
                    t['position'] = [x_rot + cx, y_rot + cy, z0 + cz]
                    
                    t['velocity'] = [float(vx), float(vy), float(vz)]
                    t['group_id'] = name_prefix
                
                objects.extend(obj_targets)
                placed = True
            attempts += 1
            
        if not placed:
            print(f"Warning: Could not place {name_prefix} due to crowding.")

    # 1. Towers
    for i in range(config['num_towers']):
        try_place_object(f"Tower_{i}", generate_cell_tower, min_dist=50.0, 
                         custom_args={'rng': rng, 'satellite_grazing_angle_deg': sat_angle, 'radar_center_freq_hz': center_freq})
    
    # 2. WiFi
    for i in range(config['num_wifi']):
        try_place_object(f"WiFi_{i}", generate_wifi_router, min_dist=10.0, z_offset=rng.uniform(3.0, 5.0),
                         custom_args={'rng': rng, 'satellite_grazing_angle_deg': sat_angle, 'radar_center_freq_hz': center_freq})
        
    # 3. Cars
    for i in range(config['num_cars']):
        try_place_object(f"Car_{i}", generate_car, min_dist=10.0, is_moving=True, speed_range=(10.0, 20.0),
                         custom_args={'radar_center_freq_hz': center_freq})
        
    # 4. People
    for i in range(config['num_people']):
        try_place_object(f"Person_{i}", generate_person, min_dist=2.0, is_moving=True, speed_range=(1.0, 2.0),
                         custom_args={'rng': rng, 'satellite_grazing_angle_deg': sat_angle, 'radar_center_freq_hz': center_freq})

    # 5. Aircraft (Pre-defined trajectories overhead)
    for i in range(config['num_jets']):
        cx = rng.uniform(-area_size[0]/2, area_size[0]/2)
        cy = rng.uniform(-area_size[1]/2, area_size[1]/2)
        cz = rng.uniform(3000.0, 5000.0) # Altitude
        
        speed = rng.uniform(200.0, 300.0)
        heading = rng.uniform(0, 2 * math.pi)
        vx = speed * math.cos(heading)
        vy = speed * math.sin(heading)
        
        targets = generate_fighter_jet(center_pos=(0, 0, 0), name_prefix=f"Jet_{i}", radar_center_freq_hz=center_freq)
        
        cos_h = math.cos(heading)
        sin_h = math.sin(heading)
                
        for t in targets:
            x0, y0, z0 = t['position']
            x_rot = x0 * cos_h - y0 * sin_h
            y_rot = x0 * sin_h + y0 * cos_h
            t['position'] = [x_rot + cx, y_rot + cy, z0 + cz]
            t['velocity'] = [float(vx), float(vy), 0.0]
            t['group_id'] = f"Jet_{i}"
        objects.extend(targets)
        
    for i in range(config['num_stealth_jets']):
        cx = rng.uniform(-area_size[0]/2, area_size[0]/2)
        cy = rng.uniform(-area_size[1]/2, area_size[1]/2)
        cz = rng.uniform(5000.0, 8000.0) # Higher Altitude
        
        speed = rng.uniform(250.0, 350.0)
        heading = rng.uniform(0, 2 * math.pi)
        vx = speed * math.cos(heading)
        vy = speed * math.sin(heading)
        
        targets = generate_stealth_fighter(center_pos=(0, 0, 0), name_prefix=f"StealthJet_{i}", radar_center_freq_hz=center_freq)
        
        cos_h = math.cos(heading)
        sin_h = math.sin(heading)
                
        for t in targets:
            x0, y0, z0 = t['position']
            x_rot = x0 * cos_h - y0 * sin_h
            y_rot = x0 * sin_h + y0 * cos_h
            t['position'] = [x_rot + cx, y_rot + cy, z0 + cz]
            t['velocity'] = [float(vx), float(vy), 0.0]
            t['group_id'] = f"StealthJet_{i}"
        objects.extend(targets)
        
    return objects

def simulate_time_steps(initial_scene, num_steps, dt):
    """
    Evolves the scene forward in time.
    """
    timeline = []
    
    # Store initial state
    timeline.append(initial_scene)
    
    current_scene = initial_scene
    
    for step in range(1, num_steps):
        next_scene = []
        for target in current_scene:
            # Deep copy to avoid modifying previous time steps
            new_target = dict(target)
            new_target['position'] = [
                target['position'][0] + target['velocity'][0] * dt,
                target['position'][1] + target['velocity'][1] * dt,
                target['position'][2] + target['velocity'][2] * dt
            ]
            next_scene.append(new_target)
            
        timeline.append(next_scene)
        current_scene = next_scene
        
    return timeline

def main():
    config = {
        'seed': 42,
        'radar_center_freq_hz': 10.0e9, # Defaulting to X-Band (10 GHz) for the simulation
        'area_size': (500, 500),      # 500m x 500m patch
        'satellite_grazing_angle_deg': 45.0,
        'sigma_zero': 0.05,             # Suburban L/S-band ~ -13 dB base
        'num_clutter_pts': 500,
        'num_people': 15,
        'num_wifi': 10,
        'num_cars': 10,
        'num_towers': 2,
        'num_jets': 2,
        'num_stealth_jets': 1,
        'cpi_sec': 5.0,
        'dt': 0.5
    }
    
    rng = np.random.default_rng(config['seed'])
    
    print("Generating background clutter...")
    total_area = config['area_size'][0] * config['area_size'][1]
    
    # Scale clutter up or down based on frequency profile
    clutter_scale = interpolate_rcs_scale('standard', config['radar_center_freq_hz'])
    expected_clutter_rcs = total_area * config['sigma_zero'] * clutter_scale
    
    clutter = generate_distributed_clutter(rng, config['area_size'], config['num_clutter_pts'], expected_clutter_rcs)
    
    print("Initializing dynamic targets and emitters...")
    dynamic_objects = initialize_scene(rng, config)
    
    initial_scene = clutter + dynamic_objects
    
    num_steps = int(config['cpi_sec'] / config['dt'])
    print(f"Simulating {num_steps} time steps...")
    
    timeline = simulate_time_steps(initial_scene, num_steps, config['dt'])
    
    print("Saving to city_simulation.json...")
    with open('city_simulation.json', 'w') as f:
        json.dump({
            'config': config,
            'timeline': timeline
        }, f, indent=2)
        
    print(f"Done! Saved {len(timeline[0])} targets per frame.")

if __name__ == "__main__":
    main()
