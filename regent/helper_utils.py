import pandas as pd

def generate_nominal_channel_mapping_csv(
    input_csv_path: str,
    output_csv_path: str = "channel_mapping.csv",
    enable_sim_room_router: bool = False
):
    """
    Generate a channel mapping CSV for Nominal using a channel CSV containing:
    - "Display Name"
    - "Origin Topic"
    - "Measurement Path"
    
    Outputs a CSV with:
    - "Display Name"
    - "New Name" in the format:
        {DOMAIN}.{ORIGIN_TOPIC}.{MEASUREMENT_PATH}
      or, if the domain is unknown:
        {ORIGIN_TOPIC}.{MEASUREMENT_PATH}

    Args:
        input_csv_path: Path to your input CSV.
        output_csv_path: Path to write the output CSV.
        enable_sim_room_router: Use True if sim room router should be enabled.
    """
    # Load CSV
    df = pd.read_csv(input_csv_path)

    # Domain setup
    if enable_sim_room_router:
        VMC_1_DOMAIN = VMC_2_DOMAIN = VMS_DOMAIN = TIS_DOMAIN = 1
    else:
        VMC_1_DOMAIN, VMC_2_DOMAIN, VMS_DOMAIN, TIS_DOMAIN = 21, 22, 20, 17

    topic_mapping = {
        'VMS': {
            'AGG_CONTEXT': {'domains': [VMC_1_DOMAIN]},
            'AGG_FS_OUTPUT': {'domains': [VMC_1_DOMAIN]},
            'AGG_MEASUREMENTS': {'domains': [VMC_1_DOMAIN]},
            'AGG_EXTERN_INPUTS': {'domains': [VMC_1_DOMAIN]},
            'EXTERN_INPUTS': {'domains': [VMS_DOMAIN]},
            'DIAGNOSTICS_HANDOVER': {'domains': [VMS_DOMAIN]},
            'DIAGNOSTICS_HEARTBEAT': {'domains': [VMS_DOMAIN]},
            'ALERT_ACK': {'domains': [VMS_DOMAIN]},
            'ACTIVE_ALERT_LIST': {'domains': [VMC_1_DOMAIN]},
            'AGG_HEALTH': {'domains': [VMC_1_DOMAIN, VMC_2_DOMAIN]},
            'VMC_HW_INFO_MEAS': {'domains': [VMC_1_DOMAIN, VMC_2_DOMAIN]},
            'VCSI_HEALTH_CONTEXT': {'domains': [VMC_1_DOMAIN, VMC_2_DOMAIN]},
            'PTP_HEALTH_MONITOR_CONTEXT': {'domains': [VMC_1_DOMAIN, VMC_2_DOMAIN]},
            'PTP_TIME_KEEPER_CONTEXT': {'domains': [VMC_1_DOMAIN, VMC_2_DOMAIN]},
        },
        'TIS': {
            'DAQ_A_AI217_0_topic': {'domains': [TIS_DOMAIN]},
            'DAQ_A_AI217_1_topic': {'domains': [TIS_DOMAIN]},
            'DAQ_B_AI217_0_topic': {'domains': [TIS_DOMAIN]},
            'DAQ_B_AI217_1_topic': {'domains': [TIS_DOMAIN]},
            'DAQ_B_AI222_2_topic': {'domains': [TIS_DOMAIN]},
            'DAQ_A_PTP_STATUS': {'domains': [TIS_DOMAIN]},
            'DAQ_B_PTP_STATUS': {'domains': [TIS_DOMAIN]},
            'FOSS_topic': {'domains': [TIS_DOMAIN]},
            'load_pin_forward_starboard': {'domains': [TIS_DOMAIN]},
            'load_pin_forward_port': {'domains': [TIS_DOMAIN]},
            'load_pin_rear_starboard': {'domains': [TIS_DOMAIN]},
            'load_pin_rear_port': {'domains': [TIS_DOMAIN]},
            'PTP_HEALTH_MONITOR_CONTEXT': {'domains': [TIS_DOMAIN]},
            'VEHICLE_DATA_RECORDER_CONTEXT': {'domains': [TIS_DOMAIN]},
            'TIS_DATA_RECORDER_CONTEXT': {'domains': [TIS_DOMAIN]},
            'HARDWARE_HEALTH_INFO': {'domains': [TIS_DOMAIN]},
        },
    }

    # Build Origin Topic -> Domain lookup
    origin_topic_to_domain = {}
    for _, topics in topic_mapping.items():
        for topic_name, props in topics.items():
            origin_topic_to_domain[topic_name] = props['domains'][0]

    # Build new channel names
    def build_new_name(row):
        origin_topic = row["Origin Topic"]
        measurement_path = row["Measurement Path"]
        domain = origin_topic_to_domain.get(origin_topic)
        if domain is None:
            return f"{origin_topic}.{measurement_path}"
        else:
            return f"{domain}.{origin_topic}.{measurement_path}"

    df["New Name"] = df.apply(build_new_name, axis=1)

    # Extract and save
    mapping_df = df[["Display Name", "New Name"]]
    mapping_df.to_csv(output_csv_path, index=False)

    print(f"Channel mapping CSV generated: {output_csv_path}")

generate_nominal_channel_mapping_csv(
    input_csv_path="/Users/ashenoy/Code/impl-demo/regent/mml.csv",
    output_csv_path="/Users/ashenoy/Code/impl-demo/regent/channel_mapping.csv")