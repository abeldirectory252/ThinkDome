#!/bin/busybox sh
# ThinkDome MicroVM Early Boot Init Script
# Uses Busybox & OverlayFS for isolated guest execution

echo "[ThinkDome Initramfs] Starting guest boot sequence..."

LOWER_RO_DEVICE=/dev/vda
WRITABLE_RW_DEVICE=/dev/vdb

LOWER_RO=/mnt/ro
WRITABLE_RW=/mnt/rw
UPPER=${WRITABLE_RW}/upper
WORK=${WRITABLE_RW}/work

NEWROOT=${WRITABLE_RW}/newroot
NEWROOT_LOWER_RO=${NEWROOT}/ro
NEWROOT_WRITABLE_RW=${NEWROOT}/rw

# Mount essential pseudo-filesystems
echo "[ThinkDome Initramfs] Mounting dev, proc, sys..."
/bin/busybox mount -t devtmpfs none /dev
/bin/busybox mount -t proc proc /proc
/bin/busybox mount -t sysfs sysfs /sys
/bin/busybox mount -t tmpfs inittemp /mnt

# 1. Mount read-only base rootfs
echo "[ThinkDome Initramfs] Mounting read-only rootfs (${LOWER_RO_DEVICE}) -> ${LOWER_RO}"
/bin/busybox mkdir -p ${LOWER_RO}
/bin/busybox mount -t ext4 ${LOWER_RO_DEVICE} ${LOWER_RO} 2>/dev/null || /bin/busybox mount -o loop ${LOWER_RO_DEVICE} ${LOWER_RO} 2>/dev/null

# 2. Mount writable stateful disk
echo "[ThinkDome Initramfs] Mounting writable device (${WRITABLE_RW_DEVICE}) -> ${WRITABLE_RW}"
/bin/busybox mkdir -p ${WRITABLE_RW}
/bin/busybox mount -t ext4 ${WRITABLE_RW_DEVICE} ${WRITABLE_RW} 2>/dev/null || /bin/busybox mount -t tmpfs tmpfs ${WRITABLE_RW}

# 3. Setup OverlayFS directories
echo "[ThinkDome Initramfs] Setting up OverlayFS upper and work dirs..."
/bin/busybox mkdir -p ${UPPER} ${WORK} ${NEWROOT} ${NEWROOT_LOWER_RO} ${NEWROOT_WRITABLE_RW}

# 4. Construct OverlayFS mount
echo "[ThinkDome Initramfs] Mounting OverlayFS into ${NEWROOT}"
/bin/busybox mount -t overlay overlay -o lowerdir=${LOWER_RO},upperdir=${UPPER},workdir=${WORK} ${NEWROOT} 2>/dev/null

if [ $? -ne 0 ]; then
    echo "[ThinkDome Initramfs] OverlayFS mount failed, using fallback single-root mount..."
    /bin/busybox mount --bind ${LOWER_RO} ${NEWROOT} 2>/dev/null || /bin/busybox mount --bind / ${NEWROOT}
fi

echo "[ThinkDome Initramfs] Pivoting root via switch_root -> ${NEWROOT} /sbin/init"
exec /bin/busybox switch_root ${NEWROOT} /sbin/init 2>/dev/null || exec /bin/busybox sh
