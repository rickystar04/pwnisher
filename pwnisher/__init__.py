import threading
import time
import logging
import os
import re

config = None
known_aps = {}
known_aps_lock = threading.Lock()
_cpu_stats = {}
_name = None




def cpu_load(tag=None):
    """
    Returns the current cpuload
    """
    if tag and tag in _cpu_stats.keys():
        parts0 = _cpu_stats[tag]
    else:
        parts0 = _cpu_stat()
        time.sleep(0.1)     # only need to sleep when no tag
    parts1 = _cpu_stat()
    if tag:
        _cpu_stats[tag] = parts1

    parts_diff = [p1 - p0 for (p0, p1) in zip(parts0, parts1)]
    user, nice, sys, idle, iowait, irq, softirq, steal, _guest, _guest_nice = parts_diff
    idle_sum = idle + iowait
    non_idle_sum = user + nice + sys + irq + softirq + steal
    total = idle_sum + non_idle_sum
    return non_idle_sum / total

def temperature(celsius=True):
    with open('/sys/class/thermal/thermal_zone0/temp', 'rt') as fp:
        temp = int(fp.read().strip())
    c = int(temp / 1000)
    return c if celsius else ((c * (9 / 5)) + 32)

def mem_usage():
    with open('/proc/meminfo') as fp:
        for line in fp:
            line = line.strip()
            if line.startswith("MemTotal:"):
                kb_mem_total = int(line.split()[1])
            if line.startswith("MemFree:"):
                kb_mem_free = int(line.split()[1])
            if line.startswith("Buffers:"):
                kb_main_buffers = int(line.split()[1])
            if line.startswith("Cached:"):
                kb_main_cached = int(line.split()[1])
        kb_mem_used = kb_mem_total - kb_mem_free - kb_main_cached - kb_main_buffers
        return round(kb_mem_used / kb_mem_total, 1)
    
def _cpu_stat():
    """
    Returns the split first line of the /proc/stat file
    """
    with open('/proc/stat', 'rt') as fp:
        return list(map(int, fp.readline().split()[1:]))


def restart(mode):
    logging.warning("restarting in %s mode ...", mode)
    mode = mode.upper()
    if mode == 'AUTO':
        os.system("touch /root/.pwnagotchi-auto")
    else:
        os.system("touch /root/.pwnagotchi-manual")

    os.system("service bettercap restart")
    time.sleep(1)
    #os.system("service pwnagotchi restart")

def uptime():
    with open('/proc/uptime') as fp:
        return int(fp.read().split('.')[0])