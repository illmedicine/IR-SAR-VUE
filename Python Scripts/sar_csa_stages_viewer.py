import numpy as np
import matplotlib.pyplot as plt
from matplotlib.widgets import RadioButtons, Button, Slider
import os

def main():
    print("Launching Standalone CSA Interactive Viewer...")
    filename = 'sar_csa_stages.npz'
    
    if not os.path.exists(filename):
        print(f"Error: {filename} not found. Run sar_csa_processing.py first.")
        return
        
    print(f"Loading {filename}...")
    data = np.load(filename)

    # 1. Define Stages and Load Data
    steps = [
        {'id': '01_raw_time', 'title': '1. Raw Baseband', 'xlabel': 'Fast Time (Samples)', 'ylabel': 'Slow Time (Pulses)', 'extent': None},
        {'id': '02_range_doppler', 'title': '2. Range-Doppler', 'xlabel': 'Fast Time (Samples)', 'ylabel': 'Doppler (Hz)', 'extent': None},
        {'id': '03_cs_applied_rd', 'title': '3. Chirp Scaling Applied', 'xlabel': 'Fast Time', 'ylabel': 'Doppler (Hz)', 'extent': None},
        {'id': '04_rc_rcmc_2df', 'title': '4. Range Comp + RCMC (2D-Freq)', 'xlabel': 'Range Freq (Hz)', 'ylabel': 'Doppler (Hz)', 'extent': None},
        {'id': '05_rc_rcmc_rd', 'title': '5. RCMC Corrected (Range-Doppler)', 'xlabel': 'Range (m)', 'ylabel': 'Doppler (Hz)', 'extent': None},
        {'id': '06_ac_applied_rd', 'title': '6. Azimuth Comp Applied', 'xlabel': 'Range (m)', 'ylabel': 'Doppler (Hz)', 'extent': None},
        {'id': '07_focused_image', 'title': '7. Focused Image', 'xlabel': 'Cross-Range (m)', 'ylabel': 'Range (m)', 'extent': None}
        # Note: Focused image axes are swapped to match standard SAR orientation (Range on Y, Cross-Range on X, or vice-versa depending on matrix transpose)
    ]
    
    # Store matrix data in the dictionary
    for s in steps:
        s['data'] = data[s['id']]
        
    # Get Axis Data for Image (Step 7)
    range_axis = data['range_axis']
    cross_range_axis = data['cross_range_axis']
    
    # 2. Setup Figure and Global State
    fig = plt.figure(figsize=(15, 9))
    plt.subplots_adjust(left=0.25, bottom=0.15, right=0.9)
    
    current_idx = 6 # Start on focused image
    use_db = True
    show_phase = False
    
    im_handle = None
    cbar_handle = None
    zoom_limits = {} # Cache xy limits per stage
    ui_refs = {}
    
    # Dedicated Plot Axis
    ax_main = fig.add_axes([0.25, 0.1, 0.65, 0.8])
    
    def get_sliced_data(data_mat, xlim, ylim, extent=None):
        """Extracts the subset of the matrix visible in the current viewport for stats."""
        rows, cols = data_mat.shape
        
        # Determine coordinate mapping boundaries
        if extent is None:
            x_min, x_max, y_min, y_max = 0, cols, 0, rows
        else:
            x_min, x_max, y_min, y_max = extent
            
        x0_Use = max(min(xlim[0], xlim[1]), min(x_min, x_max))
        x1_Use = min(max(xlim[0], xlim[1]), max(x_min, x_max))
        y0_Use = max(min(ylim[0], ylim[1]), min(y_min, y_max))
        y1_Use = min(max(ylim[0], ylim[1]), max(y_min, y_max))
        
        if (x1_Use <= x0_Use) or (y1_Use <= y0_Use):
            return np.array([0])
            
        # Map boundaries to array indices
        x_range = abs(x_max - x_min) + 1e-9
        y_range = abs(y_max - y_min) + 1e-9
        
        c0 = int((x0_Use - min(x_min, x_max)) / x_range * cols)
        c1 = int((x1_Use - min(x_min, x_max)) / x_range * cols)
        r0 = int((y0_Use - min(y_min, y_max)) / y_range * rows)
        r1 = int((y1_Use - min(y_min, y_max)) / y_range * rows)
        
        c0, c1 = max(0, min(cols, c0)), max(0, min(cols, c1))
        r0, r1 = max(0, min(rows, r0)), max(0, min(rows, r1))
        
        c_start, c_end = sorted([c0, c1])
        r_start, r_end = sorted([r0, r1])
        if c_end <= c_start: c_end = c_start + 1
        if r_end <= r_start: r_end = r_start + 1
            
        return data_mat[r_start:r_end, c_start:c_end]

    def update_clim(event=None):
        """Calculates dynamic contrast limits based ONLY on the currently zoomed/visible data."""
        nonlocal im_handle
        if im_handle is None: return
        
        if hasattr(event, 'name') and event.name in ('xlim_changed', 'ylim_changed'):
             zoom_limits[current_idx] = (ax_main.get_xlim(), ax_main.get_ylim())
             
        xlim = ax_main.get_xlim()
        ylim = ax_main.get_ylim()
        step = steps[current_idx]
        
        # We need to know if the data was transposed for imshow
        is_transposed = (current_idx < 6)
        raw_mat = step['data']
        plot_mat = raw_mat.T if is_transposed else raw_mat
        
        subset = get_sliced_data(plot_mat, xlim, ylim, extent=step['extent'])
        
        if subset.size == 0: return

        if show_phase:
             im_handle.set_clim(-np.pi, np.pi)
             fig.canvas.draw_idle()
             return

        if use_db:
            val_data = 20 * np.log10(np.abs(subset) + 1e-12)
            vmax = np.percentile(val_data, 99.9)
            # Use dynamic range slider value
            dr_val = ui_refs['slider_dr'].val if 'slider_dr' in ui_refs else 35.0
            vmin = vmax - dr_val 
        else:
            val_data = np.abs(subset)
            vmax = np.percentile(val_data, 99.9)
            vmin = 0
            
        im_handle.set_clim(vmin, vmax)
        fig.canvas.draw_idle()

    def update_view():
        """Fully re-draws the visualization when the array stage or view mode changes."""
        nonlocal im_handle, cbar_handle
        
        step = steps[current_idx]
        data_mat = step['data']
        
        # Stage 7 (Final Image) is natively loaded as (Azimuth, Range).
        # We want to display (Cross-Range, Range). Let's transpose it if necessary.
        
        if current_idx < 6:
            # Stages 1-6 are generally (Azimuth/SlowTime, Range/FastTime).
            # We transpose them so Range/FastTime is on X-axis, and Azimuth is on Y-axis.
            data_to_plot = data_mat.T 
            extent = None
        else:
            # Final Image: (Azimuth, Range). 
            # We transpose to make Cross-Range X and Range Y.
            data_to_plot = data_mat.T
            extent = [cross_range_axis[0], cross_range_axis[-1], range_axis[0], range_axis[-1]]
            step['extent'] = extent
        
        if show_phase:
            plot_data = np.angle(data_to_plot)
            cmap = 'hsv'
            lbl = f"Phase (rad)"
            ui_refs['btn_phase_obj'].label.set_text("Mode: Phase")
        else:
            if use_db:
                plot_data = 20 * np.log10(np.abs(data_to_plot) + 1e-12)
                cmap = 'bone'
                lbl = f"Magnitude (dB)"
                ui_refs['btn_log_obj'].label.set_text("Scale: Log (dB)")
                ui_refs['btn_phase_obj'].label.set_text("Mode: Mag")
            else:
                plot_data = np.abs(data_to_plot)
                cmap = 'gray'
                lbl = f"Magnitude (Linear)"
                ui_refs['btn_log_obj'].label.set_text("Scale: Linear")
                ui_refs['btn_phase_obj'].label.set_text("Mode: Mag")
        
        if im_handle is None:
            im_handle = ax_main.imshow(plot_data, aspect='auto', cmap=cmap, origin='lower', extent=extent)
            cbar_handle = fig.colorbar(im_handle, ax=ax_main)
            
            # Connect pan/zoom hooks
            ax_main.callbacks.connect('xlim_changed', update_clim)
            ax_main.callbacks.connect('ylim_changed', update_clim)
        else:
            im_handle.set_data(plot_data)
            im_handle.set_cmap(cmap)
            if extent is not None:
                im_handle.set_extent(extent)
            else:
                rows, cols = plot_data.shape
                im_handle.set_extent((0, cols, 0, rows))
                
        cbar_handle.set_label(lbl)
        ax_main.set_title(step['title'])
        ax_main.set_xlabel(step['xlabel'])
        ax_main.set_ylabel(step['ylabel'])
        
        # Restore Zoom State for this specific step if it exists
        if current_idx in zoom_limits:
            lx, ly = zoom_limits[current_idx]
            ax_main.set_xlim(lx)
            ax_main.set_ylim(ly)
        else:
            # Auto-scale view to full extent
            if extent is not None:
                ax_main.set_xlim(extent[0], extent[1])
                ax_main.set_ylim(extent[2], extent[3])
            else:
                rows, cols = plot_data.shape
                ax_main.set_xlim(0, cols)
                ax_main.set_ylim(0, rows)
                
        update_clim()
        fig.canvas.draw_idle()

    # --- UI Callbacks ---
    def on_radio_clicked(label):
        nonlocal current_idx
        for i, s in enumerate(steps):
            if s['title'] == label:
                current_idx = i
                break
        update_view()
        
    def toggle_log(event):
        nonlocal use_db
        use_db = not use_db
        update_view()

    def toggle_phase(event):
        nonlocal show_phase
        show_phase = not show_phase
        update_view()
        
    def reset_zoom(event):
        if current_idx in zoom_limits:
            del zoom_limits[current_idx]
        update_view()

    # --- Build UI Layout ---
    rax = plt.axes([0.02, 0.5, 0.18, 0.40], facecolor='lightgoldenrodyellow')
    radio = RadioButtons(rax, [s['title'] for s in steps])
    radio.on_clicked(on_radio_clicked)
    
    ax_log = plt.axes([0.02, 0.35, 0.18, 0.08])
    btn_log = Button(ax_log, 'Scale: Log (dB)')
    btn_log.on_clicked(toggle_log)
    ui_refs['btn_log_obj'] = btn_log
    
    ax_phase = plt.axes([0.02, 0.25, 0.18, 0.08])
    btn_phase = Button(ax_phase, 'Mode: Mag')
    btn_phase.on_clicked(toggle_phase)
    ui_refs['btn_phase_obj'] = btn_phase
    
    ax_reset = plt.axes([0.02, 0.15, 0.18, 0.08])
    btn_reset = Button(ax_reset, 'Reset Zoom')
    btn_reset.on_clicked(reset_zoom)
    
    # Dynamic Range Slider
    ax_slider_dr = plt.axes([0.35, 0.04, 0.45, 0.03])
    slider_dr = Slider(ax_slider_dr, 'Dynamic Range (dB)', 5.0, 100.0, valinit=5.0)
    slider_dr.on_changed(lambda val: update_clim())
    ui_refs['slider_dr'] = slider_dr
    
    # Sync initial state
    radio.set_active(current_idx)
    update_view()
    
    plt.show()

if __name__ == "__main__":
    main()
