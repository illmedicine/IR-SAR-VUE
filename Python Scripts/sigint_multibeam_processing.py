import os
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
from scipy.ndimage import zoom, gaussian_filter
from scipy.fft import fft2, ifft2, fftshift
from scipy.special import j1
import json





def clean_algorithm(img, psf, n_iter=100, loop_gain=0.2):
    residual = np.copy(img)
    clean_map = np.zeros_like(img)
    psf_peak_idx = np.unravel_index(np.argmax(psf), psf.shape)
    psf_peak_val = psf[psf_peak_idx]
    # Use a simpler relative threshold so soft physical gradients aren't prematurely statistically terminated
    noise_floor_cutoff = 0.05 * np.max(img)
    
    for _ in range(n_iter):
        idx = np.unravel_index(np.argmax(residual), residual.shape)
        peak_val = residual[idx]
        if peak_val <= noise_floor_cutoff: break
        
        subtracted_val = peak_val * loop_gain
        clean_map[idx] += subtracted_val
        shift_y = idx[0] - psf_peak_idx[0]
        shift_x = idx[1] - psf_peak_idx[1]
        shifted_psf = np.roll(psf, shift=(shift_y, shift_x), axis=(0, 1))
        residual -= subtracted_val * (shifted_psf / psf_peak_val)
    return clean_map, residual

def calculate_hsv_colormap(intensity_images, freqs):
    img_stack = np.array(intensity_images)
    total_power = np.sum(img_stack, axis=0) 
    dominant_idx = np.argmax(img_stack, axis=0)
    dominant_freq = np.array(freqs)[dominant_idx]
    f_min, f_max = min(freqs), max(freqs)
    if f_max > f_min:
        hue = 0.75 * (dominant_freq - f_min) / (f_max - f_min)
    else:
        hue = np.zeros_like(dominant_freq)
    hue = np.clip(hue, 0, 1)
    saturation = np.ones_like(hue)
    v_max = np.max(total_power)
    if v_max <= 0: v_max = 1.0
    val = np.clip((total_power / v_max) ** 0.5, 0, 1)
    
    # Physically black out pure trace numeric noise globally so background maps render crisp mathematically
    val[val < 0.15] = 0.0
    
    hsv_img = np.stack((hue, saturation, val), axis=-1)
    return mcolors.hsv_to_rgb(hsv_img), total_power, hue

def main():
    print("=============================================")
    print(" SIGINT MULTIBEAM POST-PROCESSING SUITE      ")
    print("=============================================")
    
    out_dir = "SIGINT Sim Results"
    npz_path = os.path.join(out_dir, "sigint_multibeam_data.npz")
    if not os.path.exists(npz_path):
        print(f"Error: {npz_path} not found.")
        return
        
    print("Loading simulated measurements...")
    data = np.load(npz_path)
    measured_power_mag2 = data['measured_power_mag2'] 
    x_beams, y_beams = data['x_beams'], data['y_beams']
    freqs = data['freqs']
    ap_radius = float(data['aperture_radius'])
    alt = float(data['alt'])
    
    if 'dirty_psf' in data:
        dirty_psf = data['dirty_psf']
    else:
        print("Error: Missing dynamic Dirty PSF! Rerun simulation natively first!")
        return
    
    emitters_gt = []
    if 'emitters_gt' in data:
        emitters_gt = json.loads(str(data['emitters_gt']))
        
    scene_size = x_beams[-1] - x_beams[0]
    nx_native, ny_native = len(x_beams), len(y_beams)
    dx_native, dy_native = scene_size / nx_native, scene_size / ny_native
    
    print(f"Loaded {measured_power_mag2.shape[2]} frequency bins across {ny_native}x{nx_native} physical beams.")
    
    f_start, f_end = freqs[0], freqs[-1]
    num_bands = 200 
    band_step = (f_end - f_start) / num_bands
    
    interp_factor = 4 
    nx_hr, ny_hr = nx_native * interp_factor, ny_native * interp_factor
    dx_hr, dy_hr = scene_size / nx_hr, scene_size / ny_hr
    
    deconv_images, clean_images, band_centers = [], [], []
    
    # -------------------------------------------------------------
    # STAGE 1: Full Spectrum Sweep (For Interactive HTML Viewer)
    # -------------------------------------------------------------
    print("\n[Stage 1] Conducting Full Spectrum Tomographic Sweep (200 Bands)...")
    for i in range(num_bands):
        b_min = f_start + i * band_step
        b_max = b_min + band_step
        b_mid = (b_min + b_max) / 2.0
        
        idx_mask = (freqs >= b_min) & (freqs < b_max)
        band_power_native = np.sum(measured_power_mag2[:, :, idx_mask], axis=2)
        
        psf_native = dirty_psf
        
        # CLEAN mapping must be strictly derived on absolute physical matrix blocks directly without interpolation warps
        band_power_native = np.clip(band_power_native, 0, None)
        cln_native, _ = clean_algorithm(band_power_native, psf_native, n_iter=150)
        
        # Soften raw grid explicitly to prevent spatial clipping, then cleanly Upsample analytically
        cln_soft = gaussian_filter(cln_native, sigma=0.8)
        cln_smooth = np.clip(zoom(cln_soft, interp_factor, order=3), 0, None)
        
        clean_images.append(cln_smooth)
        band_centers.append(b_mid)
        
        if i % 25 == 0: print(f"  Processed {i}/{num_bands} Bands...")
            
    print("Generating JS Viewer Cache...")
    clean_rgb, cln_pwr, cln_hue = calculate_hsv_colormap(clean_images, band_centers)
    
    viewer_data = {'power': cln_pwr.tolist(), 'hue': cln_hue.tolist(), 'min_freq': f_start, 'max_freq': f_end}
    with open(os.path.join(out_dir, "clean_data.js"), "w") as f:
        f.write(f"const CACHED_DATA = {json.dumps(viewer_data)};")

    custom_cmap = mcolors.LinearSegmentedColormap.from_list('red_violet', plt.cm.hsv(np.linspace(0, 0.75, 256)))
    ext = [-scene_size/2, scene_size/2, -scene_size/2, scene_size/2]
    
    for rgb_img, name, title in [(clean_rgb, "SIGINT_Multibeam_CLEAN_Composite.png", "Tomographic CLEAN Source Map")]:
        plt.figure(figsize=(10, 10))
        plt.imshow(rgb_img, origin='lower', extent=ext)
        plt.title(f"{title} (1.5 - 2.5 GHz)")
        plt.xlabel("Range (m)")
        plt.ylabel("Azimuth (m)")
        sm = plt.cm.ScalarMappable(cmap=custom_cmap, norm=plt.Normalize(vmin=1.5, vmax=2.5))
        sm._A = []
        plt.colorbar(sm, ax=plt.gca(), label="Dominant Frequency (GHz)", shrink=0.8).set_ticks(np.linspace(1.5, 2.5, 6))
        plt.savefig(os.path.join(out_dir, name), dpi=400, bbox_inches='tight')
        plt.close()

    # -------------------------------------------------------------
    # STAGE 2: Targeted Matching Charts (Ground Truth Band Specific)
    # -------------------------------------------------------------
    print("\n[Stage 2] Generating Custom Emitter Match Charts...")
    if emitters_gt:
        np.random.seed(42)
        # Select 5 specific emitters randomly that have relatively strong/distinct parameters 
        # (avoid overlapping entirely if possible, but random choice usually suffices)
        chosen = np.random.choice(emitters_gt, 5, replace=False)
        
        for k, e in enumerate(chosen):
            b_min = e['f'] - e['bw']/2
            b_max = e['f'] + e['bw']/2
            b_mid = e['f']
            
            idx_mask = (freqs >= b_min) & (freqs <= b_max)
            band_power_native = np.sum(measured_power_mag2[:, :, idx_mask], axis=2)
            
            psf_native = dirty_psf
            hr_power = np.clip(zoom(band_power_native, interp_factor, order=3), 0, None)
            
            # Perfect mathematical tracking unconditionally locks to native index physics  
            band_power_native = np.clip(band_power_native, 0, None)
            cln_native, _ = clean_algorithm(band_power_native, psf_native, n_iter=150)
            
            # Anti-aliasing native delta points before massive order=3 spline mapping bounds  
            cln_soft = gaussian_filter(cln_native, sigma=0.8)
            cln_smooth = np.clip(zoom(cln_soft, interp_factor, order=3), 0, None)
            
            plt.figure(figsize=(24, 5))
            
            # 1. Raw
            plt.subplot(141)
            plt.imshow(10*np.log10(hr_power/np.max(hr_power)+1e-9), extent=ext, origin='lower', cmap='turbo', vmin=-30)
            plt.title(f"Target Band:\n{b_min/1e6:.1f} - {b_max/1e6:.1f} MHz")
            plt.xlabel("Range (m)")
            plt.ylabel("Azimuth (m)")
            
            # 2. Gradient
            grad_y, grad_x = np.gradient(hr_power)
            plt.subplot(142)
            plt.imshow(np.sqrt(grad_x**2 + grad_y**2), extent=ext, origin='lower', cmap='hot')
            plt.title("Spatial Gradient")
            
            # 3. CLEAN
            plt.subplot(143)
            plt.imshow(cln_smooth, extent=ext, origin='lower', cmap='magma')
            plt.title("CLEAN Processing")
            
            # 4. GT Overlay
            plt.subplot(144)
            # Faint background of all emitters 
            plt.scatter([eg['x'] for eg in emitters_gt], [eg['y'] for eg in emitters_gt], 
                        c='gray', marker='.', alpha=0.3, label="Other Spectrum Emitters")
            
            # Highlight ones strictly overlapping THIS particular matched band bounds
            actives = [eg for eg in emitters_gt if eg['f'] + eg['bw']/2 > b_min and eg['f'] - eg['bw']/2 < b_max]
            if actives:
                plt.scatter([ac['x'] for ac in actives], [ac['y'] for ac in actives], 
                            facecolors='none', edgecolors='lime', marker='o', s=200, linewidth=2, label="Band Active Ground Truth")
            plt.xlim(ext[0], ext[1])
            plt.ylim(ext[2], ext[3])
            # Set aspect ratio equal to match map plotting perfectly
            plt.gca().set_aspect('equal', adjustable='box')
            # Add strict background so it looks like a map and not floating points
            plt.gca().set_facecolor('#111')
            
            # Align formatting perfectly mathematically with identical decimal layouts
            plt.title(f"Band Layout ({b_min/1e6:.1f}-{b_max/1e6:.1f} MHz)")
            plt.xlabel("Range (m)")
            plt.legend(loc="upper right", prop={'size': 8})
            
            plt.tight_layout()
            plt.savefig(os.path.join(out_dir, f"Targeted_Match_{k}_Comparison.png"), dpi=300)
            plt.close()
            
    print("Processing complete! Outputs saved in SIGINT Sim Results.")

if __name__ == "__main__":
    main()
