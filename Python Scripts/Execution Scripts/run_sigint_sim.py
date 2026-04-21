import subprocess
import os
import sys

def main():
    print("========================================")
    print("  SIGINT MULTIBEAM IMAGE PROCESSING     ")
    print("========================================")
    
    # 1. Run Simulation Environment
    print("\n[Stage 1] Calculating Multibeam Expected Array Power...")
    res = subprocess.run([sys.executable, "sigint_sim_env.py"])
    if res.returncode != 0:
        print("Error in simulation. Exiting.")
        return
        
    print("\n[Stage 2] Running Deconvolution and CLEAN Algorithms...")
    res = subprocess.run([sys.executable, "sigint_multibeam_processing.py"])
    if res.returncode != 0:
        print("Error in processing. Exiting.")
        return
        
    print("\nSIGINT Pipeline Complete!")

if __name__ == "__main__":
    main()
