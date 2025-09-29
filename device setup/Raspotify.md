# Complete Raspotify Bluetooth Speaker Setup Guide

## Prerequisites

- Raspberry Pi with Raspberry Pi OS
- Spotify Premium account
- Bluetooth speaker
- Internet connection

## Step 1: Install Raspotify

### Install using the official script:

```bash
curl -sL https://dtcooper.github.io/raspotify/install.sh | sh
```

### Enable the service:

```bash
sudo systemctl enable raspotify
```

## Step 2: Install Bluetooth Audio Support

### Install BlueALSA for Bluetooth audio:

```bash
sudo apt update
sudo apt install bluez-alsa-utils -y
sudo systemctl enable bluealsa
sudo systemctl start bluealsa
```

## Step 3: Connect Bluetooth Speaker

### Enter Bluetooth control:

```bash
bluetoothctl
```

### In bluetoothctl, run these commands:

```bash
power on
agent on
default-agent
scan on
# Wait for your speaker to appear, note its MAC address
pair XX:XX:XX:XX:XX:XX    # Replace with your speaker's MAC
trust XX:XX:XX:XX:XX:XX
connect XX:XX:XX:XX:XX:XX
exit
```

## Step 4: Configure System Audio for Bluetooth

### Create ALSA configuration:

```bash
sudo nano /etc/asound.conf
```

### Add this content (replace MAC address with yours):

```
pcm.!default {
    type plug
    slave.pcm {
        type bluealsa
        device "XX:XX:XX:XX:XX:XX"
        profile "a2dp"
        rate 44100
    }
}

ctl.!default {
    type bluealsa
}
```

## Step 5: Configure Raspotify

### Edit Raspotify configuration:

```bash
sudo nano /etc/raspotify/conf
```

### Find and modify these lines (uncomment by removing #):

```bash
# Device name as it appears in Spotify
LIBRESPOT_NAME="RaspberryPi-BT"

# Device type
LIBRESPOT_DEVICE_TYPE=speaker

# Audio backend
LIBRESPOT_BACKEND=alsa

# Audio device (use default since we configured system-wide)
LIBRESPOT_DEVICE=default

# Audio quality - lower bitrate for stable Bluetooth
LIBRESPOT_BITRATE=96

# Audio format
LIBRESPOT_FORMAT=S16

# Volume settings
LIBRESPOT_MIXER_TYPE=softvol
LIBRESPOT_INITIAL_VOLUME=70

# Disable audio caching to save SD card
LIBRESPOT_DISABLE_AUDIO_CACHE=
```

## Step 6: Start and Test

### Start all services:

```bash
sudo systemctl restart bluealsa
sudo systemctl restart raspotify
```

### Check service status:

```bash
sudo systemctl status raspotify
```

### Test system audio:

```bash
speaker-test -t wav -c 2
```

## Step 7: Connect from Spotify

1. Open Spotify on any device (phone, computer, web player)
2. Start playing music
3. Look for the "Connect to device" option (speaker icon)
4. Select "RaspberryPi-BT" from the list
5. Music should play through your Bluetooth speaker

## Troubleshooting

### If Raspotify fails to start:

```bash
# Check logs
sudo journalctl -u raspotify -f

# Ensure Bluetooth speaker is connected
bluetoothctl connect XX:XX:XX:XX:XX:XX
```

### If audio quality is poor or cuts out:

1. Lower bitrate further in `/etc/raspotify/conf`:

   ```bash
   LIBRESPOT_BITRATE=96
   ```

2. Check Bluetooth connection quality:

   ```bash
   hcitool rssi XX:XX:XX:XX:XX:XX
   ```

3. Ensure no 2.4GHz WiFi interference (use 5GHz WiFi or ethernet)

### If other system audio doesn't use Bluetooth:

Check that `/etc/asound.conf` contains your speaker's MAC address and restart:

```bash
sudo systemctl restart alsa-state
```

## Auto-reconnect Bluetooth Speaker on Boot

### Create auto-connect service:

```bash
sudo nano /etc/systemd/system/bluetooth-connect.service
```

### Add this content:

```ini
[Unit]
Description=Connect Bluetooth Speaker
After=bluetooth.service bluealsa.service
Requires=bluetooth.service

[Service]
Type=oneshot
ExecStart=/usr/bin/bluetoothctl connect XX:XX:XX:XX:XX:XX
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
```

### Enable the service:

```bash
sudo systemctl enable bluetooth-connect.service
```

## Final Notes

- Raspotify will start automatically on boot
- All system audio will route through the Bluetooth speaker
- Use any Spotify client to control playback remotely
- The Pi appears as "RaspberryPi-BT" in Spotify's device list
- Requires Spotify Premium for Connect functionality

## Key Configuration Files

- **Raspotify config**: `/etc/raspotify/conf`
- **System audio config**: `/etc/asound.conf`
- **Service logs**: `sudo journalctl -u raspotify -f`
- **Bluetooth control**: `bluetoothctl`
