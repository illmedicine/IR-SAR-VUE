"""
STAP Scenario Interactive Viewer
Features: 
- Loads CSA processed DPCA data from STAP Results folder.
- Dynamic layout and statistics on zoom/pan.
- DPCA Cancellation ratio tracking.
"""
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.widgets import RadioButtons, Button, Slider, TextBox
import os
import sys

def main():
    scenario_name = "default_stap_scenario"
    if len(sys.argv) > 1:
        scenario_name = sys.argv[1]
        
    print(f"Launching STAP Viewer for Scenario: {scenario_name}")
    
    # --- 1. Load Data ---
    fname = os.path.join("STAP Results", scenario_name, "stap_focused_results.npz")
    if not os.path.exists(fname):
        print(f"Data file {fname} not found. Please run the pipeline first.")
        return

    print("Loading raw NPZ dictionary...")
    data = np.load(fname)
    raw_s1 = data['slc1']
    raw_s2 = data['slc2']
    
    # 4K Maximum Resolution Viewport Lock
    MAX_PIXELS = 3840
    sz_rg, sz_az = raw_s1.shape
    
    stride_rg = max(1, sz_rg // MAX_PIXELS)
    stride_az = max(1, sz_az // MAX_PIXELS)
    
    print(f"Applying robust 4K dynamic down-sampling exactly to [rg:{stride_rg}, az:{stride_az}] to prevent memory explosion...")
    
    slc1 = raw_s1[::stride_rg, ::stride_az].T.copy()
    slc2 = raw_s2[::stride_rg, ::stride_az].T.copy()
    rax = data['range_axis'][::stride_rg].copy()
    cax = data['cross_range'][::stride_az].copy()
    
    del data, raw_s1, raw_s2
    import gc
    gc.collect()
    
    extent = [rax[0], rax[-1], cax[0], cax[-1]]
    
    # --- 2. Derived Products Storage ---
    class SARData:
        def __init__(self, s1, s2):
            self.s1 = s1
            self.s2 = s2
            self.cal_phase = 0.0
            self.mask_thresh = 99.5
            self.compute_all()
            
        def compute_all(self):
            s2_cal = self.s2 * np.exp(1j * self.cal_phase)
            dpca_diff = self.s1 - s2_cal
            dpca_mag = np.abs(dpca_diff)
            ati_interf = self.s1 * np.conj(s2_cal)
            ati_phase = np.angle(ati_interf)
            
            # HARDCODED radial velocity mapping: 
            # v_r = (lam * Phi) / (4 * pi * t_B). With alt=350km, d_ATI=1.92m, PRF=8000Hz, f0=2GHz:
            # v_r ≈ 47.74 * Phi (m/s)
            VEL_PHASE_SCALAR = 47.74
            ati_vel = ati_phase * VEL_PHASE_SCALAR
            
            # Extract targeted percentile DPCA threshold for masking ATI returns securely
            thresh = np.percentile(dpca_mag, self.mask_thresh)
            masked_ati = np.where(dpca_mag > thresh, ati_vel, np.nan)
            
            self.prods = {
                'Ch1 Magnitude': np.abs(self.s1),
                'Ch1 Phase': np.angle(self.s1),
                'Ch2 Magnitude': np.abs(s2_cal),
                'Ch2 Phase': np.angle(s2_cal),
                'DPCA Magnitude': dpca_mag,
                'DPCA Phase': np.angle(dpca_diff),
                'ATI Radial Vel (m/s)': ati_vel,
                'ATI Radial Vel (Masked)': masked_ati
            }
            
        def get(self, mode):
            return self.prods.get(mode)

    sar = SARData(slc1, slc2)

    # --- 3. UI State ---
    state = {
        'mode': 'Ch1 Magnitude',
        'scale': 'dB',
        'im_handle': None,
        'cbar_handle': None,
        'zoom_stats_enabled': True
    }

    # --- 4. Main Figure Setup ---
    fig = plt.figure(figsize=(15, 9))

    ax_main = fig.add_axes([0.28, 0.15, 0.57, 0.75])
    ax_cbar = fig.add_axes([0.88, 0.15, 0.02, 0.75])

    # --- 5. Statistics Function ---
    def print_visible_stats(ax):
        if not state['zoom_stats_enabled']: return
        
        xlim = ax.get_xlim()
        ylim = ax.get_ylim()
        
        r_mask = (rax >= min(xlim)) & (rax <= max(xlim))
        c_mask = (cax >= min(ylim)) & (cax <= max(ylim))
        
        r_indices = np.where(r_mask)[0]
        c_indices = np.where(c_mask)[0]
        
        if len(r_indices) == 0 or len(c_indices) == 0:
            return
            
        raw_data = sar.get(state['mode'])
        visible_raw = raw_data[np.ix_(c_indices, r_indices)]
        
        print(f"\n--- Visible Stats: {state['mode']} ---")
        
        if 'Vel' in state['mode']:
            # Suppress all-NaN slice warnings safely
            with np.errstate(all='ignore'):
                print(f"Mean: {np.nanmean(visible_raw):.2f} m/s")
                print(f"Std: {np.nanstd(visible_raw):.2f} m/s")
                print(f"Range: [{np.nanmin(visible_raw):.2f}, {np.nanmax(visible_raw):.2f}]")
        elif 'Phase' in state['mode']:
            with np.errstate(all='ignore'):
                print(f"Mean: {np.nanmean(visible_raw):.4f} rad")
                print(f"Std: {np.nanstd(visible_raw):.4f} rad")
        else:
            if state['scale'] == 'dB':
                data = 20 * np.log10(visible_raw + 1e-12)
                unit = "dB"
            else:
                data = visible_raw
                unit = "Units"
                
            print(f"Mean: {np.mean(data):.2f} {unit}")
            print(f"Std: {np.std(data):.2f} {unit}")
            print(f"Range: [{np.min(data):.2f}, {np.max(data):.2f}]")
            
            if 'DPCA' in state['mode']:
                ref_mag = sar.get('Ch1 Magnitude')[np.ix_(c_indices, r_indices)]
                ratio = np.mean(ref_mag) / (np.mean(visible_raw) + 1e-9)
                ratio_db = 20 * np.log10(ratio + 1e-9)
                print(f"Local Cancellation Ratio: {ratio:.2f} ({ratio_db:.1f} dB)")

        if state['im_handle']:
            if 'Vel' in state['mode']:
                max_v = np.pi * 47.74
                vmin, vmax = -max_v, max_v
            elif 'Phase' in state['mode']:
                vmin, vmax = -np.pi, np.pi
            else:
                vmax = np.percentile(data, 99.9)
                vmin = vmax - 60 if state['scale'] == 'dB' else 0
            state['im_handle'].set_clim(vmin, vmax)
            fig.canvas.draw_idle()

    def on_lim_change(event_ax):
        print_visible_stats(event_ax)

    ax_main.callbacks.connect('xlim_changed', on_lim_change)
    ax_main.callbacks.connect('ylim_changed', on_lim_change)

    # --- 6. Plot Updating ---
    def update_plot():
        mode = state['mode']
        scale = state['scale']
        
        data_raw = sar.get(mode)
        
        if 'Vel' in mode:
            display_data = data_raw
            max_v = np.pi * 47.74
            vmin, vmax = -max_v, max_v
            cmap = 'jet'
            if 'Masked' in mode:
                import copy
                cmap = copy.copy(plt.get_cmap('jet'))
                cmap.set_bad(color='black')
            lbl = "Radial Velocity (m/s)"
        elif 'Phase' in mode:
            display_data = data_raw
            vmin, vmax = -np.pi, np.pi
            cmap = 'hsv'
            if 'Masked' in mode:
                import copy
                cmap = copy.copy(plt.get_cmap('hsv'))
                cmap.set_bad(color='black')
            lbl = f"{mode} (rad)"
        else:
            if scale == 'dB':
                display_data = 20 * np.log10(data_raw + 1e-12)
                vmax = np.percentile(display_data, 99.9)
                vmin = vmax - 60
                cmap = 'magma' if 'DPCA' in mode else 'bone'
                lbl = f"{mode} (dB)"
            else:
                display_data = data_raw
                vmax = np.percentile(display_data, 99.9)
                vmin = 0
                cmap = 'magma' if 'DPCA' in mode else 'gray'
                lbl = f"{mode} (Linear)"

        if state['im_handle'] is None:
            state['im_handle'] = ax_main.imshow(display_data, aspect='auto', origin='lower', 
                                                extent=extent, cmap=cmap, vmin=vmin, vmax=vmax)
            state['cbar_handle'] = fig.colorbar(state['im_handle'], cax=ax_cbar)
        else:
            state['im_handle'].set_data(display_data)
            state['im_handle'].set_cmap(cmap)
            state['im_handle'].set_clim(vmin, vmax)
        
        state['cbar_handle'].set_label(lbl)
        ax_main.set_title(f"STAP Scene: {mode}")
        ax_main.set_xlabel("Ground Range (m)")
        ax_main.set_ylabel("Cross-Range (m)")
        
        fig.canvas.draw_idle()
        print_visible_stats(ax_main)

    # --- 7. Controls ---
    ax_radio_mode = fig.add_axes([0.02, 0.55, 0.18, 0.35], facecolor='#FFF8DC')
    modes = ['Ch1 Magnitude', 'Ch1 Phase', 'Ch2 Magnitude', 'Ch2 Phase', 'DPCA Magnitude', 'DPCA Phase', 'ATI Radial Vel (m/s)', 'ATI Radial Vel (Masked)']
    radio_mode = RadioButtons(ax_radio_mode, modes)
    def set_mode(label):
        state['mode'] = label
        update_plot()
    radio_mode.on_clicked(set_mode)

    ax_radio_scale = fig.add_axes([0.02, 0.45, 0.18, 0.1], facecolor='#E0FFFF')
    radio_scale = RadioButtons(ax_radio_scale, ['dB', 'Linear'])
    def set_scale(label):
        state['scale'] = label
        update_plot()
    radio_scale.on_clicked(set_scale)

    ax_btn_bal = fig.add_axes([0.7, 0.05, 0.1, 0.04])
    btn_bal = Button(ax_btn_bal, 'Auto-Balance')
    def do_balance(event):
        print("Calibrating Channel Phase...")
        avg_interf = np.mean(slc1 * np.conj(slc2))
        sar.cal_phase = np.angle(avg_interf)
        print(f"Applied Phase Offset: {np.degrees(sar.cal_phase):.3f} deg")
        sar.compute_all()
        update_plot()
    btn_bal.on_clicked(do_balance)

    ax_btn_reset = fig.add_axes([0.82, 0.05, 0.06, 0.04])
    btn_reset = Button(ax_btn_reset, 'Reset')
    def do_reset(event):
        ax_main.set_xlim(rax[0], rax[-1])
        ax_main.set_ylim(cax[0], cax[-1])
        update_plot()
    btn_reset.on_clicked(do_reset)

    ax_mask_slider = fig.add_axes([0.02, 0.35, 0.18, 0.05], facecolor='#F0FFF0')
    slider_mask = Slider(ax_mask_slider, 'Mask %', 90.0, 100.0, valinit=99.5)
    
    ax_mask_text = fig.add_axes([0.02, 0.28, 0.18, 0.05], facecolor='#F0FFF0')
    text_mask = TextBox(ax_mask_text, 'Exact %: ', initial='99.5000')

    def do_mask_update(val):
        sar.mask_thresh = slider_mask.val
        formatted_val = f"{slider_mask.val:.4f}"
        if text_mask.text != formatted_val:
            text_mask.set_val(formatted_val)
        if 'Masked' in state['mode']:
            sar.compute_all()
            update_plot()
            
    def do_text_update(text):
        try:
            val = float(text)
            if 90.0 <= val <= 100.0:
                if abs(slider_mask.val - val) > 1e-6:
                    slider_mask.set_val(val)
        except ValueError:
            pass

    slider_mask.on_changed(do_mask_update)
    text_mask.on_submit(do_text_update)
    
    update_plot()
    plt.show()

if __name__ == "__main__":
    main()
