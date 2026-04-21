import sys

with open("sigint_sim_env.py", "r") as f:
    code = f.read()

# Replace the injected sys.argv block mapped incorrectly before with the clean loop mapping
old_block = """    import sys
    num_emitters = int(sys.argv[1]) if len(sys.argv) > 1 else 2
    scatter_area = float(sys.argv[2]) if len(sys.argv) > 2 else CFG['area_size_m'][0]
    
    print(f"Placing {num_emitters} standard emitters globally inside each of the {len(PROTOCOLS)} protocol bands natively...")
    for idx, chosen_proto in enumerate(PROTOCOLS):
        for sub_id in range(num_emitters):
            cx = rng.uniform(-scatter_area/2, scatter_area/2)
            cy = rng.uniform(-scatter_area/2, scatter_area/2)"""

new_block = """    print(f"Placing {num_emitters} standard emitters globally inside each of the {len(PROTOCOLS)} protocol bands natively...")
    for idx, chosen_proto in enumerate(PROTOCOLS):
        for sub_id in range(num_emitters):
            cx = rng.uniform(-scatter_area_m/2, scatter_area_m/2)
            cy = rng.uniform(-scatter_area_m/2, scatter_area_m/2)"""

if old_block in code:
    code = code.replace(old_block, new_block)
    with open("sigint_sim_env.py", "w") as f:
        f.write(code)
    print("Success patching!")
else:
    print("Could not find block!")
