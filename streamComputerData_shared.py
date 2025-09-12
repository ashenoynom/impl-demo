import nominal as nm
import numpy as np
import psutil
import random
import shutil
import speedtest
import threading
import time
from datetime import datetime, timedelta
from multiprocessing.pool import ThreadPool
from time import sleep
from urllib3.util.retry import Retry


# DEMO API KEY
TOKEN = "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJodHRwczovL2F1dGguZ292Lm5vbWluYWwuaW8iLCJzdWIiOiJyaS5hdXRobi5jZXJ1bGVhbi1zdGFnaW5nLnVzZXIuMDgyNzQ3NjQtOGQ1Ni00MWVmLTk4ZGItYTA0YzNiM2Q1OGVhIiwibm9taW5hbCI6eyJ1c2VyX3V1aWQiOiIwODI3NDc2NC04ZDU2LTQxZWYtOThkYi1hMDRjM2IzZDU4ZWEiLCJvcmdhbml6YXRpb25fdXVpZCI6Ijc5YzJjZGQxLTRjY2QtNDI4OC1iMDZiLTI0ZTkwMmE2YjNhZiJ9LCJleHAiOjE3NTE5MTUzMDYsImF1ZCI6Imh0dHBzOi8vYXBpLmdvdi5ub21pbmFsLmlvIn0.NaQ3G2aLQZR2v_PjfBocMWGqVoW11Z762p7p8vrPcOTs6cgGOCVSvWzgnsFos_dffRw0Fl4fKmep79ScZ3fDHvW0iX2qwb-lXwnRrf1WR7GwERt23zSdJzqZOZY9n7bsjBd4chV_008IHlWjWPy9gLyk_RQGNj928hzJuPKEjCyf0vij3sqLhKYCAy-znNtElzV4q6wu0F31dF0l-4hVFxa4MyOC9Jbn-SgsOka6zVZ9Cn5VhJQWPRfwaAljLFoRQv8gN1kLrdmucwoiWppPoMNH9O3az6S8rdTs6VPkFOB_cFiEDgmf2CUEsgiHZGK-FZC4k1gISOcEZr6LrYHKGg" # CHANGE this to your API Key
CONNECTION_RID = 'ri.data-source.cerulean-staging.connection.3a9d3190-f06a-4309-82b5-ff3f5a602f6e' # base-station-streaming
BASE_URL = 'https://api.gov.nominal.io/api'
WORKSPACE_RID="ri.security.cerulean-staging.workspace.79c2cdd1-4ccd-4288-b06b-24e902a6b3af" # Demo workspace

client = nm.NominalClient.create(
    base_url=BASE_URL, 
    token=TOKEN,
    workspace_rid=WORKSPACE_RID
)
connection = client.get_connection(CONNECTION_RID)

MACHINE_NAME = "anish-mac"
interface = "en0"  # Replace with your network interface
lock = threading.Lock()

# Signal Parameters
sample_rate = 300  # Sample rate in Hz
duration = 10
frequencies = [50, 100, 120]  # Frequencies to mix (in Hz)
noise_level = 2    # Amplitude of the noise


def generate_signal():

    # Generate time array
    t = np.linspace(0, duration, int(sample_rate * duration), endpoint=False)

    with connection.get_write_stream(max_wait=timedelta(seconds=1)) as stream:
        while True:

            # Generate mixed signal
            signal = sum(np.sin(2 * np.pi * f * t) for f in frequencies)

            # Generate white noise
            noise = noise_level * np.random.normal(size=signal.shape)
            
            # Combine signal and noise
            signal = signal + noise

            # Normalize to -1.0 to 1.0
            signal /= np.max(np.abs(signal))

            for sample in signal:

                stream.enqueue(
                    channel_name="Signal", 
                    timestamp=datetime.now(), 
                    value=sample,
                )
                sleep(1/sample_rate)


def get_network_stats(interface):
    net_io_counters = psutil.net_io_counters(pernic=True)
    if interface in net_io_counters:
        stats = net_io_counters[interface]
        return stats.bytes_sent, stats.bytes_recv


def calculate_throughput(interface, interval=1):
    sent_before, recv_before = get_network_stats(interface)
    time.sleep(interval)
    sent_after, recv_after = get_network_stats(interface)

    sent_throughput = (sent_after - sent_before) / interval
    recv_throughput = (recv_after - recv_before) / interval

    return sent_throughput, recv_throughput

def calculate_network_throughput():
    sent_throughput, recv_throughput = calculate_throughput(interface)

    print(f"Sent throughput: {sent_throughput / 1024:.2f} KB/s")
    print(f"Received throughput: {recv_throughput / 1024:.2f} KB/s")
    return float(sent_throughput / 1024), float(recv_throughput / 1024)

def stream_network_speed():
    st = speedtest.Speedtest(secure=True)

    while True:
        network_data = {}
        try:
            st.download()
            st.upload()
            network_data['Download_Speed_Mbps'] = st.results.download / 1000000
            network_data['Upload_Speed_Mbps'] = st.results.upload / 1000000
            current_time = datetime.now()
            # Stream to Nominal
            with connection.get_write_stream(max_wait=timedelta(seconds=1)) as stream:
                stream.enqueue_from_dict(timestamp=current_time, channel_values=network_data)
                print(f"Download Speed: {network_data['Download_Speed_Mbps']}")
                print(f"Upload Speed: {network_data['Upload_Speed_Mbps']}")
        except Exception as e:
            print(f"Failed to measure network speeds: {e}")

def generate_sensor_data():

    # Start timer
    start_time = time.perf_counter()
    while True:
        sensor_data = {}
        try:
            random.seed(int(time.time())) # Set random seed using current time
            current_time = datetime.now()
            
            # Stream Battery Info
            battery = psutil.sensors_battery()
            sensor_data['Battery_Percentage'] = float(battery.percent)
            sensor_data['Power_Mode'] = 1.0 if battery.power_plugged else 0.0
            
            if battery.power_plugged:
                sensor_data['Charging_ON'] = "CHARGING_ON"
            else:
                sensor_data['Charging_OFF'] = "CHARGING_OFF"
                
            sensor_data['Computer_Name'] = "nick-mac"
            sensor_data['RAM_Used_GB'] = float(psutil.virtual_memory()[3] / 1000000000)

            # Simulate temperature of battery pack around 10 deg C
            sensor_data['Battery_Temperature'] = random.gauss(10, 0.5)
            # Simulate Voltage of battery around 24V
            sensor_data['Battery_Voltage'] = random.gauss(20, 0.1)
            # # Simulate current fluctuation around a stable value for each battery pack
            sensor_data['Battery_Current'] = random.gauss(5, 0.01)
            sensor_data['Battery_Capacity'] = float(sensor_data['Battery_Voltage'] * sensor_data['Battery_Current'] / 120)

            # # Simulate packet telemetry
            sensor_data['Packets_Received'] = float(random.randint(10000, 100000))  # Instantaneous number of packets received (random range)
            sensor_data['Packets_Dropped'] = float(random.randint(0, int(sensor_data['Packets_Received'] * 0.01)))  # Increased probability of dropped packets (5%)
           
            # Get Network throughput
            sent_throughput, recv_throughput = calculate_network_throughput()
            sensor_data['Sent_Throughput_KBps'] = sent_throughput
            sensor_data['Received_Throughput_KBps'] = recv_throughput
            print(sensor_data)
            # Stream all data to Nominal
            with connection.get_write_stream(max_wait=timedelta(seconds=1)) as stream:
                stream.enqueue_from_dict(timestamp=current_time, channel_values=sensor_data,tags={"machine_name": MACHINE_NAME})
            
            elapsed_seconds = int(time.perf_counter() - start_time)
            print(f"Streamed Sensor data as a dictionary - been streaming for {elapsed_seconds} seconds")
            
            time.sleep(0.5)  # Telemetry at 2Hz
        except Exception as e:
            print(f"Sensor data collection error: {e}")

def calculate_cpu_usage():
    while True:
        cpu_percentage = psutil.cpu_percent(1)
        # cpu_temperature = psutil.sensors_temperatures()['nvme'][0].current
        current_time = datetime.now()
        
        with connection.get_write_stream(max_wait=timedelta(seconds=1)) as stream:
            stream.enqueue(channel_name=f"CPU_Usage", timestamp=current_time, value=float(cpu_percentage), tags={"machine_name": MACHINE_NAME})
            # stream.enqueue(channel_name=f"CPU Temperature", timestamp=current_time, value=float(cpu_temperature), tags={"machine_name": MACHINE_NAME})
            stream.enqueue(channel_name=f"RAM_Used_GB", timestamp=datetime.now(), value=float(psutil.virtual_memory()[3]/1000000000), tags={"machine_name": MACHINE_NAME})

            time.sleep(0.5)  # Telemetry at 2Hz

def calculate_storage():
    while True:
            
        total, used, free = shutil.disk_usage("/")
        current_time = datetime.now()
        
        with connection.get_write_stream(max_wait=timedelta(seconds=1)) as stream:
            # Stream storage
            stream.enqueue(
                channel_name=f"Disk_Used_GB",
                timestamp=current_time,
                value=float(used // (2**30)),
                tags={"machine_name": MACHINE_NAME}
            )
            stream.enqueue(
                channel_name=f"Disk_Free_GB",
                timestamp=current_time,
                value=float(free // (2**30)),
                tags={"machine_name": MACHINE_NAME}
            )
        sleep(30)

def main():
    sensor_thread = threading.Thread(target=generate_sensor_data)
    cpu_thread = threading.Thread(target=calculate_cpu_usage)
    network_thread = threading.Thread(target=stream_network_speed)
    storage_thread = threading.Thread(target=calculate_storage)
    signal_thread = threading.Thread(target=generate_signal)

    sensor_thread.start()
    cpu_thread.start()
    network_thread.start()
    storage_thread.start()
    signal_thread.start()

    sensor_thread.join()
    cpu_thread.join()
    network_thread.join()
    storage_thread.join()
    signal_thread.join()

if __name__ == "__main__":
    main()
