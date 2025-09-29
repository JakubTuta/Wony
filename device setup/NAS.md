# Complete Step-by-Step Guide: External Drive to NAS Setup

## Part 1: Identify and Fix Your External Drive

### Step 1: Find Your External Drive

```bash
# List all storage devices
lsblk

# Get detailed partition information
sudo fdisk -l

# Check filesystem types and UUIDs
sudo blkid
```

Look for your external drive (usually `/dev/sda` with partitions like `/dev/sda1`, `/dev/sda2`).

### Step 2: Identify the Correct Partition

```bash
# Get detailed info about your external drive
sudo fdisk -l /dev/sda

# Check filesystem information
sudo blkid /dev/sda*
```

From the output, identify:

- **Device path** (e.g., `/dev/sda2`)
- **Filesystem type** (e.g., `ntfs`, `ext4`)
- **UUID** (unique identifier)
- **Label** (drive name)

### Step 3: Fix Drive Issues (If Any)

For **NTFS drives** with errors:

```bash
# Install NTFS tools
sudo apt update
sudo apt install ntfs-3g

# Fix NTFS filesystem
sudo ntfsfix /dev/sda2
sudo ntfsfix --clear-dirty /dev/sda2
```

For **ext4 drives** with errors:

```bash
# Check and fix ext4 filesystem
sudo fsck -f /dev/sda2
```

## Part 2: Set Up Automatic Mounting

### Step 4: Create Mount Point and Test Mount

```bash
# Create mount directory
sudo mkdir -p /mnt/nas-drive

# Test manual mount (replace with your partition)
sudo mount /dev/sda2 /mnt/nas-drive

# Check if successful
df -h | grep nas-drive

# Check contents
ls -la /mnt/nas-drive

# If successful, unmount for next step
sudo umount /mnt/nas-drive
```

### Step 5: Set Up Automatic Mounting

```bash
# Get the UUID of your drive (note it down)
sudo blkid /dev/sda2

# Edit fstab for automatic mounting
sudo nano /etc/fstab

# Add this line at the end (replace YOUR-UUID and filesystem type):
```

**For NTFS drives:**

```bash
UUID=YOUR-UUID /mnt/nas-drive ntfs-3g defaults,uid=1000,gid=1000,umask=0022,nofail,x-systemd.device-timeout=10 0 0
```

**For ext4 drives:**

```bash
UUID=YOUR-UUID /mnt/nas-drive ext4 defaults,nofail 0 2
```

### Step 6: Test Automatic Mounting

```bash
# Test the fstab entry
sudo mount -a

# Check if mounted
df -h | grep nas-drive

# If successful, reboot to test
sudo reboot

# After reboot, check again
df -h | grep nas-drive
```

## Part 3: Install and Configure Samba

### Step 7: Install Samba

```bash
# Update system
sudo apt update

# Install Samba
sudo apt install samba samba-common-bin -y

# Backup original configuration
sudo cp /etc/samba/smb.conf /etc/samba/smb.conf.backup
```

### Step 8: Configure Samba Share

```bash
# Edit Samba configuration
sudo nano /etc/samba/smb.conf
```

**Add this at the end of the file:**

```ini
[NAS-Drive]
   comment = External NAS Drive
   path = /mnt/nas-drive
   browseable = yes
   read only = no
   guest ok = yes
   public = yes
   create mask = 0777
   directory mask = 0777
   force user = pi
   force group = pi
   valid users = pi
   writeable = yes
```

**Update the global section (find `[global]` and modify/add these lines):**

```ini
[global]
   workgroup = WORKGROUP
   server string = Raspberry Pi NAS
   netbios name = RASPI-NAS
   security = user
   map to guest = bad user
   dns proxy = no
   server role = standalone server
   passdb backend = tdbsam

   # Windows compatibility
   client min protocol = SMB2
   server min protocol = SMB2

   # Performance tuning
   socket options = TCP_NODELAY IPTOS_LOWDELAY
```

### Step 9: Set Up Users and Permissions

```bash
# Replace 'pi' with your actual username (e.g., 'tuta')
USERNAME=$(whoami)

# Create sambashare group
sudo groupadd sambashare

# Add your user to the group
sudo usermod -a -G sambashare $USERNAME

# Set proper ownership of the drive
sudo chown -R $USERNAME:sambashare /mnt/nas-drive

# Set proper permissions
sudo chmod -R 755 /mnt/nas-drive

# Create Samba password for your user
sudo smbpasswd -a $USERNAME

# Enable the user
sudo smbpasswd -e $USERNAME
```

### Step 10: Test and Start Samba

```bash
# Test configuration for errors
sudo testparm

# Start Samba services
sudo systemctl start smbd nmbd

# Enable services to start on boot
sudo systemctl enable smbd nmbd

# Check service status
sudo systemctl status smbd nmbd
```

### Step 11: Configure Firewall (if enabled)

```bash
# Check firewall status
sudo ufw status

# If active, allow Samba
sudo ufw allow samba
```

## Part 4: Connect from Windows PC

### Step 12: Get Your Raspberry Pi's IP Address

```bash
# Get IP address
hostname -I

# Or use this command
ip addr show | grep "inet " | grep -v 127.0.0.1
```

Note down the IP address (e.g., `192.168.1.100`).

### Step 13: Test Connection Locally

```bash
# Test Samba shares locally
smbclient -L //localhost -U $USERNAME

# Test connecting to your share
smbclient //localhost/NAS-Drive -U $USERNAME
```

### Step 14: Connect from Windows PC

#### Method 1: Direct Access

1. Open **File Explorer**
2. In the address bar, type: `\\YOUR-PI-IP\NAS-Drive`
   - Example: `\\192.168.1.100\NAS-Drive`
3. When prompted for credentials, enter:
   - **Username:** your Pi username (e.g., `pi` or `tuta`)
   - **Password:** the Samba password you created

#### Method 2: Map Network Drive (Recommended)

1. Open **File Explorer**
2. Right-click **"This PC"** → **"Map network drive"**
3. Choose a **drive letter** (e.g., `Z:`)
4. **Folder:** `\\YOUR-PI-IP\NAS-Drive`
5. ✅ Check **"Reconnect at sign-in"**
6. ✅ Check **"Connect using different credentials"**
7. Click **"Finish"**
8. Enter your credentials when prompted
9. The drive should now appear as **"Network Drive (Z:)"** in This PC

#### Method 3: Add Network Location

1. Right-click **"This PC"** → **"Add a network location"**
2. Click **"Next"** → **"Choose a custom network location"**
3. Enter: `\\YOUR-PI-IP\NAS-Drive`
4. Give it a name and finish the wizard

## Part 5: Verification and Troubleshooting

### Step 15: Final Verification

```bash
# Check if drive is mounted
df -h | grep nas-drive

# Check Samba services
sudo systemctl status smbd nmbd

# Check available shares
smbclient -L //YOUR-PI-IP -U $USERNAME

# Test file creation
touch /mnt/nas-drive/test-file.txt
ls -la /mnt/nas-drive/
```

### Step 16: Test After Reboot

```bash
# Reboot your Pi
sudo reboot

# After reboot, verify everything is working:
df -h | grep nas-drive                    # Drive should be auto-mounted
sudo systemctl status smbd nmbd          # Services should be running
ls -la /mnt/nas-drive                     # Files should be accessible
```

## Common Troubleshooting

### If Windows can't connect:

```bash
# Check Samba logs
sudo tail -20 /var/log/samba/log.smbd

# Restart Samba services
sudo systemctl restart smbd nmbd

# Check your Pi's IP hasn't changed
hostname -I
```

### If drive doesn't auto-mount:

```bash
# Check fstab entry
cat /etc/fstab | grep nas-drive

# Try manual mount
sudo mount -a

# Check for errors
dmesg | grep sda
```

### Windows-specific fixes:

1. **Enable network discovery** in Windows network settings
2. **Clear Windows credentials:**
   ```cmd
   net use * /delete
   ```
3. **Try with IP address** instead of computer name

## Summary

Your NAS setup should now:

- ✅ Auto-mount external drive on boot
- ✅ Start Samba services automatically
- ✅ Be accessible from Windows as a network drive
- ✅ Survive power cycles and reboots
- ✅ Have proper permissions and security

Access your NAS from Windows using: `\\YOUR-PI-IP\NAS-Drive`

## Additional Notes

### Security Considerations

- Change default Samba passwords regularly
- Consider disabling guest access for better security
- Use strong passwords for user accounts
- Consider setting up different users for different access levels

### Performance Optimization

For better performance, you can add these settings to `/etc/sysctl.conf`:

```bash
net.core.rmem_default = 262144
net.core.rmem_max = 16777216
net.core.wmem_default = 262144
net.core.wmem_max = 16777216
```

### Backup Important Data

Always backup important data before making significant changes to your NAS setup. Consider setting up automated backup scripts for critical files.

### Regular Maintenance

- Check drive health periodically with `sudo smartctl -a /dev/sda`
- Monitor disk space usage with `df -h`
- Review Samba logs occasionally for any issues
- Keep your Raspberry Pi OS updated with `sudo apt update && sudo apt upgrade`
