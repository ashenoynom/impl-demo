# Handle Vehicle Data Router/Sim Room data router switch
if enable_sim_room_router:
    VMC_1_DOMAIN = VMC_2_DOMAIN = VMS_DOMAIN = TIS_DOMAIN = 1
    domains_with_subnets = [
        {'id': 1, 'subnet': 100},
        {'id': 18, 'subnet': 150}
      ]
else:
    VMC_1_DOMAIN, VMC_2_DOMAIN, VMS_DOMAIN, TIS_DOMAIN = 21, 22, 20, 17
    domains_with_subnets = [
        {'id': 17, 'subnet': 150},
        {'id': 18, 'subnet': 150},
        {'id': 20, 'subnet': 3},
        {'id': 21, 'subnet': 3},
        {'id': 22, 'subnet': 3}
    ]

# FIXME import topic -> type mapping from somewhere
topic_mapping = {
  'VMS': {
    'AGG_CONTEXT': { 'domains': [VMC_1_DOMAIN], 'type': 'REGENT_DDS::VMS::AggContextBlock' },
    'AGG_FS_OUTPUT': { 'domains': [VMC_1_DOMAIN], 'type': 'REGENT_DDS::VMS::AggFlightStackOutputBlock' },
    'AGG_MEASUREMENTS': { 'domains': [VMC_1_DOMAIN], 'type': 'REGENT_DDS::VMS::AggMeasurementBlock' },
    'AGG_EXTERN_INPUTS': { 'domains': [VMC_1_DOMAIN], 'type': 'REGENT_DDS::VMS::AggregateExternalInputs' },
    'EXTERN_INPUTS': { 'domains': [VMS_DOMAIN], 'type': 'REGENT_DDS::VCS::external_inputs', 'exclusive': True },
    'DIAGNOSTICS_HANDOVER': { 'domains': [VMS_DOMAIN], 'type': 'REGENT_DDS::VMS::DiagnosticsHandover', 'exclusive': True },
    'DIAGNOSTICS_HEARTBEAT': { 'domains': [VMS_DOMAIN], 'type': 'REGENT_DDS::VMS::DiagnosticsHeartbeat', 'exclusive': True },
    'ALERT_ACK': { 'domains': [VMS_DOMAIN], 'type': 'REGENT_DDS::VMS::AlertAck' },
    'ACTIVE_ALERT_LIST': { 'domains': [VMC_1_DOMAIN], 'type': 'REGENT_DDS::VMS::ActiveAlertList' },
    'AGG_HEALTH': { 'domains': [VMC_1_DOMAIN, VMC_2_DOMAIN], 'type': 'REGENT_DDS::VMS::AggregateHealth' },
    'VMC_HW_INFO_MEAS': { 'domains': [VMC_1_DOMAIN, VMC_2_DOMAIN], 'type': 'REGENT_DDS::VMS::VMCHardwareInfoSample' },
    'VCSI_HEALTH_CONTEXT': { 'domains': [VMC_1_DOMAIN, VMC_2_DOMAIN], 'type': 'REGENT_DDS::VMS::VCSInterfaceHealthContext' },
    'PTP_HEALTH_MONITOR_CONTEXT': { 'domains': [VMC_1_DOMAIN, VMC_2_DOMAIN], 'type': 'REGENT_DDS::VMS::PtpHealthMonitorContext' },
    'PTP_TIME_KEEPER_CONTEXT': { 'domains': [VMC_1_DOMAIN, VMC_2_DOMAIN], 'type': 'REGENT_DDS::VMS::PtpTimeKeeperContext' }
  },
  'TIS': {
    'DAQ_A_AI217_0_topic': { 'domains': [TIS_DOMAIN], 'type': 'REGENT_DDS::tis::DAQ_A_AI217_0' },
    'DAQ_A_AI217_1_topic': { 'domains': [TIS_DOMAIN], 'type': 'REGENT_DDS::tis::DAQ_A_AI217_1' },
    'DAQ_B_AI217_0_topic': { 'domains': [TIS_DOMAIN], 'type': 'REGENT_DDS::tis::DAQ_B_AI217_0' },
    'DAQ_B_AI217_1_topic': { 'domains': [TIS_DOMAIN], 'type': 'REGENT_DDS::tis::DAQ_B_AI217_1' },
    'DAQ_B_AI222_2_topic': { 'domains': [TIS_DOMAIN], 'type': 'REGENT_DDS::tis::DAQ_B_AI222_2' },
    'DAQ_A_PTP_STATUS': { 'domains': [TIS_DOMAIN], 'type': 'REGENT_DDS::TIS::DAQPTPStatus' },
    'DAQ_B_PTP_STATUS': { 'domains': [TIS_DOMAIN], 'type': 'REGENT_DDS::TIS::DAQPTPStatus' },
    'FOSS_topic': { 'domains': [TIS_DOMAIN], 'type': 'REGENT_DDS::tis::FOSS' },
    'load_pin_forward_starboard': { 'domains': [TIS_DOMAIN], 'type': 'REGENT_DDS::TIS::cyclops_load_pin' },
    'load_pin_forward_port': { 'domains': [TIS_DOMAIN], 'type': 'REGENT_DDS::TIS::cyclops_load_pin' },
    'load_pin_rear_starboard': { 'domains': [TIS_DOMAIN], 'type': 'REGENT_DDS::TIS::cyclops_load_pin' },
    'load_pin_rear_port': { 'domains': [TIS_DOMAIN], 'type': 'REGENT_DDS::TIS::cyclops_load_pin' },
    'PTP_HEALTH_MONITOR_CONTEXT': { 'domains': [TIS_DOMAIN], 'type': 'REGENT_DDS::VMS::PtpHealthMonitorContext' },
    'VEHICLE_DATA_RECORDER_CONTEXT': { 'domains': [TIS_DOMAIN], 'type': 'REGENT_DDS::TIS::VehicleDataRecorderContext' },
    'TIS_DATA_RECORDER_CONTEXT': { 'domains': [TIS_DOMAIN], 'type': 'REGENT_DDS::TIS::VehicleDataRecorderContext' },
    'HARDWARE_HEALTH_INFO': { 'domains': [TIS_DOMAIN], 'type': 'REGENT_DDS::TIS::TISHardwareInfoSample' }
  }
}