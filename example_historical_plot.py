import numpy as np
import matplotlib.pyplot as plt

# Create time vector: T-2s to T+2s, 500 points
t = np.linspace(-2, 2, 500)

# Tight, high-magnitude wiggle shifted left by ~150ms:
wiggle_center = -0.275  # -275ms
wiggle_width = 0.125    # 250ms duration
pre_T0_wiggle = 25 * np.sin(50 * (t - wiggle_center)) * np.exp(-((t - wiggle_center)/wiggle_width)**2)

# Current operation: "Test 25"
ox_injector_p_current = (
    15 + 250 * (0.5 + 0.5 * np.tanh((t + 0.3) * 4)) +
    pre_T0_wiggle +
    np.random.normal(0, 1.0, size=t.shape)
)
fuel_injector_p_current = (
    10 + 240 * (0.5 + 0.5 * np.tanh((t + 0.25) * 4)) +
    pre_T0_wiggle +
    np.random.normal(0, 1.0, size=t.shape)
)
chamber_p_current = (
    200 / (1 + np.exp(-30 * t)) +
    np.random.normal(0, 2, size=t.shape)
)

# 5x historical operations with realistic divergence
num_hist = 5
ox_injector_p_hist = []
fuel_injector_p_hist = []
chamber_p_hist = []

for i in range(num_hist):
    time_shift = np.random.normal(0, 0.03)
    amp_shift_ox = np.random.normal(0, 10)
    amp_shift_fuel = np.random.normal(0, 10)
    amp_shift_chamber = np.random.normal(0, 20)

    wiggle_noise = 25 * np.sin(50 * (t - wiggle_center + np.random.normal(0, 0.005))) * np.exp(-((t - wiggle_center)/wiggle_width)**2)

    ox_injector_p_hist.append(
        15 + amp_shift_ox + 250 * (0.5 + 0.5 * np.tanh((t + 0.3 + time_shift) * 4)) +
        wiggle_noise +
        np.random.normal(0, 2.0, size=t.shape)
    )
    fuel_injector_p_hist.append(
        10 + amp_shift_fuel + 240 * (0.5 + 0.5 * np.tanh((t + 0.25 + time_shift) * 4)) +
        wiggle_noise +
        np.random.normal(0, 2.0, size=t.shape)
    )
    chamber_p_hist.append(
        (200 + amp_shift_chamber) / (1 + np.exp(-30 * (t + time_shift))) +
        np.random.normal(0, 5, size=t.shape)
    )

# Plotting
plt.figure(figsize=(12, 6))
plt.title("Engine Startup Transient")

# Historical traces (grayscale, no label)
for i in range(num_hist):
    gray_value = 0.8 - 0.12 * i
    plt.plot(t, ox_injector_p_hist[i], color=str(gray_value), linewidth=1)
    plt.plot(t, fuel_injector_p_hist[i], color=str(gray_value), linewidth=1)
    plt.plot(t, chamber_p_hist[i], color=str(gray_value), linewidth=1)

# Current operation
plt.plot(t, ox_injector_p_current, label="Test 25 - Ox Injector P", color="blue", linewidth=2)
plt.plot(t, fuel_injector_p_current, label="Test 25 - Fuel Injector P", color="red", linewidth=2)
plt.plot(t, chamber_p_current, label="Test 25 - Chamber P", color="orange", linewidth=2)

# Event markers:
spin_line = plt.axvline(-0.75, color='purple', linestyle='--', linewidth=1.5, label="Spin (T-0.75s)")
igniter_line = plt.axvline(-0.1, color='green', linestyle='--', linewidth=1.5, label="Igniter On (T-0.1s)")
t0_line = plt.axvline(0, color='black', linestyle='--', linewidth=1.5, label="T-0")

# Labels and grid
plt.xlabel("Time (s) relative to T-0")
plt.ylabel("Pressure (bar)")
plt.xlim([-2, 2])
plt.grid(True, linestyle=':', alpha=0.7)

# Legend
plt.legend()

# Layout and show
plt.tight_layout()
plt.show()
