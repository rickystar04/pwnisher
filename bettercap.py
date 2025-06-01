import os
import time
import tomlkit
import random
import logging
import asyncio
import threading
import subprocess
import requests
import websockets

from time import sleep
from requests.auth import HTTPBasicAuth

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s [%(levelname)s] %(message)s',
)
requests.adapters.DEFAULT_RETRIES = 5

ping_timeout = 180
ping_interval = 15
max_queue = 10000

min_sleep = 0.5
max_sleep = 5.0

def decode(r, verbose_errors=True):
    try:
        return r.json()
    except Exception as e:
        if r.status_code == 200:
            logging.error("error while decoding json: error='%s' resp='%s'" % (e, r.text))
        else:
            err = "error %d: %s" % (r.status_code, r.text.strip())
            if verbose_errors:
                logging.info(err)
            raise Exception(err)
        return r.text


class Client:
    def __init__(self, config, hostname='localhost', scheme='http', port=8081, username='user', password='pass'):
        self.config = config
        self.hostname = hostname
        self.scheme = scheme
        self.port = port
        self.username = username
        self.password = password
        self.url = f"{scheme}://{hostname}:{port}/api"
        self.websocket = f"ws://{username}:{password}@{hostname}:{port}/api"
        self.auth = HTTPBasicAuth(username, password)

    def session(self, sess="session"):
        r = requests.get(f"{self.url}/{sess}", auth=self.auth)
        return decode(r)

    async def start_websocket(self, consumer):
        s = f"{self.websocket}/events"
        while True:
            logging.info("[bettercap] creating new websocket...")
            try:
                async with websockets.connect(
                    s,
                    ping_interval=ping_interval,
                    ping_timeout=ping_timeout,
                    max_queue=max_queue
                ) as ws:
                    while True:
                        try:
                            async for msg in ws:
                                try:
                                    await consumer(msg)
                                except Exception as ex:
                                    logging.debug("[bettercap] error while parsing event (%s)", ex)
                        except websockets.ConnectionClosedError:
                            try:
                                pong = await ws.ping()
                                await asyncio.wait_for(pong, timeout=ping_timeout)
                                logging.warning('[bettercap] ping OK, keeping connection alive...')
                                continue
                            except:
                                sleep_time = min_sleep + max_sleep * random.random()
                                logging.warning('[bettercap] ping error - retrying in %.1f sec', sleep_time)
                                await asyncio.sleep(sleep_time)
                                break
            except (ConnectionRefusedError, OSError):
                sleep_time = min_sleep + max_sleep * random.random()
                logging.warning('[bettercap] retrying websocket connection in %.1f sec', sleep_time)
                await asyncio.sleep(sleep_time)

    def run(self, command, verbose_errors=True):
        while True:
            try:
                r = requests.post(f"{self.url}/session", auth=self.auth, json={'cmd': command})
            except requests.exceptions.ConnectionError:
                sleep_time = min_sleep + max_sleep * random.random()
                logging.warning("[bettercap] connection error, retrying run in %.1f sec", sleep_time)
                sleep(sleep_time)
            else:
                break
        return decode(r, verbose_errors=verbose_errors)

    def start_module(self, module):
        self.run(f'{module} on')

    def iface_channels(self, ifname):
        channels = []
        phy = subprocess.getoutput(f"/sbin/iw {ifname} info | grep wiphy | cut -d ' ' -f 2")
        output = subprocess.getoutput(f"/sbin/iw phy{phy} channels | grep ' MHz' | grep -v disabled | sed 's/^.*\\[//g' | sed s/\\].*\\$//g")
        for line in output.split("\n"):
            try:
                channels.append(int(line.strip()))
            except Exception:
                pass
        return channels

    def is_module_running(self, module):
        s = self.session()
        for m in s.get('modules', []):
            if m['name'] == module:
                return m['running']
        return False

    def restart_module(self, module):
        self.run(f'{module} off; {module} on')

    def get_config(self):
        return self.config

    def _reset_wifi_settings(self):
        cfg = self.get_config()
        mon_iface = cfg['main']['iface']
        self.run(f'set wifi.interface {mon_iface}')
        self.run(f'set wifi.ap.ttl {cfg["personality"]["ap_ttl"]}')
        self.run(f'set wifi.sta.ttl {cfg["personality"]["sta_ttl"]}')
        self.run(f'set wifi.rssi.min {cfg["personality"]["min_rssi"]}')
        self.run(f'set wifi.handshakes.file {cfg["bettercap"]["handshakes"]}')
        self.run('set wifi.handshakes.aggregate false')

    def start_monitor_mode(self):
        mon_iface = "wlan0mon"
        mon_start_cmd = "startmon.sh"
        has_mon = False

        while not has_mon:
            s = self.session()
            for iface in s.get('interfaces', []):
                if iface['name'] == mon_iface:
                    logging.info("found monitor interface: %s", iface['name'])
                    has_mon = True
                    break

            if not has_mon:
                if mon_start_cmd:
                    logging.info("starting monitor interface ...")
                    subprocess.run(["bash", mon_start_cmd])
                else:
                    logging.info("waiting for monitor interface %s ...", mon_iface)
                    time.sleep(1)

        cfg = self.get_config()
        self._supported_channels = self.iface_channels(cfg['main']['iface'])
        logging.info("supported channels: %s", self._supported_channels)
        logging.info("handshakes will be collected inside %s", cfg['bettercap']['handshakes'])

        self._reset_wifi_settings()

        if self.is_module_running('wifi'):
            logging.debug("restarting wifi module ...")
            self.restart_module('wifi.recon')
            self.run('wifi.clear')
        else:
            logging.debug("starting wifi module ...")
            self.start_module('wifi.recon')

    def start_event_polling(self):
        threading.Thread(
            target=self._event_poller,
            args=(asyncio.get_event_loop(),),
            name="Event Polling",
            daemon=True
        ).start()

    def recon(self):
        cfg = self.get_config()
        recon_time = cfg['personality']['recon_time']
        channels = cfg['personality']['channels']

        if not channels:
            self._current_channel = 0
            logging.debug("RECON %ds", recon_time)
            self.run('wifi.recon.channel clear')
        else:
            logging.debug("RECON %ds ON CHANNELS %s", recon_time, ','.join(map(str, channels)))
            try:
                self.run(f'wifi.recon.channel {",".join(map(str, channels))}')
            except Exception as e:
                logging.exception("Error setting wifi.recon.channels: %s", e)


def load_toml_file(filename):
    with open(filename) as fp:
        text = fp.read()
    if "[main]" in text:
        return tomlkit.loads(text)
    else:
        import toml
        print("Converting dotted toml:", filename)
        data = toml.loads(text)
        try:
            backup = filename + ".ORIG"
            os.rename(filename, backup)
            with open(filename, "w") as fp2:
                tomlkit.dump(data, fp2)
            print("Converted to new format. Original saved at", backup)
        except Exception as e:
            print("Unable to convert to new format:", e)
        return data


def start(args):
    config = load_toml_file(args.config)
    logging.info("Loaded config: %s", config)

    hostname = config['bettercap'].get('hostname', '127.0.0.1')
    client= Client( config,
                        "127.0.0.1" if "hostname" not in config['bettercap'] else config['bettercap']['hostname'],
                        "http" if "scheme" not in config['bettercap'] else config['bettercap']['scheme'],
                        8081 if "port" not in config['bettercap'] else config['bettercap']['port'],
                        "pwnagotchi" if "username" not in config['bettercap'] else config['bettercap']['username'],
                        "pwnagotchi" if "password" not in config['bettercap'] else config['bettercap']['password'])


    logging.info("Client è di tipo: %s", type(client))

    client.session()

    logging.info("Client è di tipo: %s", type(client))


    client.start_monitor_mode()

    logging.info("Client è di tipo: %s", type(client))


    client.recon()

    logging.info("Client è di tipo: %s", type(client))


    while True:
        session = client.session("session/wifi")

        # Lista di Access Point
        for ap in session.get('aps', []):
            ssid = ap.get('ssid', '<hidden>')
            bssid = ap.get('bssid')
            rssi = ap.get('rssi')
            clients = ap.get('clients', [])
            print(f"[AP] SSID: {ssid}, BSSID: {bssid}, RSSI: {rssi}, Clients: {len(clients)}")

            # Lista di client associati
            for client in clients:
                mac = client.get('mac')
                rssi = client.get('rssi')
                print(f"    [Client] MAC: {mac}, RSSI: {rssi}")

        time.sleep(5)