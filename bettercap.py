import logging
import requests
import websockets
import asyncio
import random
import logging
import os
import tomlkit
import subprocess


from requests.auth import HTTPBasicAuth
from time import sleep

logging.basicConfig(
    level=logging.DEBUG,  # o INFO, WARNING, ERROR a seconda di cosa vuoi vedere
    format='%(asctime)s [%(levelname)s] %(message)s',
)
requests.adapters.DEFAULT_RETRIES = 5  # increase retries number

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

class Client(object):
    def __init__(self, config, hostname='localhost', scheme='http', port=8081, username='user', password='pass', ):
        self.hostname = hostname
        self.scheme = scheme
        self.port = port
        self.username = username
        self.password = password
        self.url = "%s://%s:%d/api" % (scheme, hostname, port)
        self.websocket = "ws://%s:%s@%s:%d/api" % (username, password, hostname, port)
        self.auth = HTTPBasicAuth(username, password)
      
        print(config)
        self.config=config

    # session takes optional argument to pull a sub-dictionary
    #  ex.: "session/wifi", "session/ble"
    def session(self, sess="session"):
        r = requests.get("%s/%s" % (self.url, sess), auth=self.auth)
        return decode(r)

    async def start_websocket(self, consumer):
        s = "%s/events" % self.websocket

        # More modern version of the approach below
        # logging.info("Creating new websocket...")
        # async for ws in websockets.connect(s):
        #     try:
        #         async for msg in ws:
        #             try:
        #                 await consumer(msg)
        #             except Exception as ex:
        #                     logging.debug("Error while parsing event (%s)", ex)
        #     except websockets.exceptions.ConnectionClosedError:
        #         sleep_time = max_sleep*random.random()
        #         logging.warning('Retrying websocket connection in {} sec'.format(sleep_time))
        #         await asyncio.sleep(sleep_time)
        #         continue

        # restarted every time the connection fails
        while True:
            logging.info("[bettercap] creating new websocket...")
            try:
                async with websockets.connect(s, ping_interval=ping_interval, ping_timeout=ping_timeout,
                                              max_queue=max_queue) as ws:
                    # listener loop
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
                                sleep_time = min_sleep + max_sleep*random.random()
                                logging.warning('[bettercap] ping error - retrying connection in {} sec'.format(sleep_time))
                                await asyncio.sleep(sleep_time)
                                break
            except ConnectionRefusedError:
                sleep_time = min_sleep + max_sleep*random.random()
                logging.warning('[bettercap] nobody seems to be listening at the bettercap endpoint...')
                logging.warning('[bettercap] retrying connection in {} sec'.format(sleep_time))
                await asyncio.sleep(sleep_time)
                continue
            except OSError:
                logging.warning('connection to the bettercap endpoint failed...')
                pwnagotchi.restart("AUTO")

    def run(self, command, verbose_errors=True):
        while True:
            try:
                r = requests.post("%s/session" % self.url, auth=self.auth, json={'cmd': command})
            except requests.exceptions.ConnectionError as e:
                sleep_time = min_sleep + max_sleep*random.random()
                logging.warning("[bettercap] can't run my request... connection to the bettercap endpoint failed...")
                logging.warning('[bettercap] retrying run in {} sec'.format(sleep_time))
                sleep(sleep_time)
            else:
                break

        return decode(r, verbose_errors=verbose_errors)

    def start_module(self, module):
        self.run('%s on' % module)

    def iface_channels(self, ifname):
        channels = []
        phy = subprocess.getoutput("/sbin/iw %s info | grep wiphy | cut -d ' ' -f 2" % ifname)
        output = subprocess.getoutput(r"/sbin/iw phy%s channels | grep ' MHz' | grep -v disabled | sed 's/^.*\[//g' | sed s/\].*\$//g" % phy)
        for line in output.split("\n"):
            line = line.strip()
            try:
                channels.append(int(line))
            except Exception as e:
                pass
        return channels



    def is_module_running(self, module):
        s = self.session()
        for m in s['modules']:
            if m['name'] == module:
                return m['running']
        return False


    def restart_module(self, module):
        self.run('%s off; %s on' % (module, module))
    
    def get_config(self):
        return self.config

    def _reset_wifi_settings(self):
        cfg = get_config()
        mon_iface = cfg['main']['iface']
        self.run('set wifi.interface %s' % mon_iface)
        self.run('set wifi.ap.ttl %d' % cfg['personality']['ap_ttl'])
        self.run('set wifi.sta.ttl %d' % cfg['personality']['sta_ttl'])
        self.run('set wifi.rssi.min %d' % cfg['personality']['min_rssi'])
        self.run('set wifi.handshakes.file %s' % cfg['bettercap']['handshakes'])
        self.run('set wifi.handshakes.aggregate false')

    def start_monitor_mode(self):
        mon_iface = "wlan0mon"
        mon_start_cmd = "startmon.sh"
        has_mon = False

        while has_mon is False:
            s = self.session()
            for iface in s['interfaces']:
                if iface['name'] == mon_iface:
                    logging.info("found monitor interface: %s", iface['name'])
                    has_mon = True
                    break

            if has_mon is False:
                if mon_start_cmd is not None and mon_start_cmd != '':
                    logging.info("starting monitor interface ...")
                    #self.run('!%s' % mon_start_cmd)
                    subprocess.run(["bash", "startmon.sh"])                    
                else:
                    logging.info("waiting for monitor interface %s ...", mon_iface)
                    time.sleep(1)

        cfg = get_config()
        print(cfg)
        
        self._supported_channels = self.iface_channels(cfg['main']['iface'])
        logging.info("supported channels: %s", self._supported_channels)
        logging.info("handshakes will be collected inside %s", cfg['bettercap']['handshakes'])

        self._reset_wifi_settings()

        wifi_running = self.is_module_running('wifi')
        if wifi_running:
            logging.debug("restarting wifi module ...")
            self.restart_module('wifi.recon')
            self.run('wifi.clear')
        elif not wifi_running:
            logging.debug("starting wifi module ...")
            self.start_module('wifi.recon')


    def start_event_polling(self):
        # start a thread and pass in the mainloop
        #_thread.start_new_thread(self._event_poller, (asyncio.get_event_loop(),))
        threading.Thread(target=self._event_poller, args=(asyncio.get_event_loop(),), name="Event Polling", daemon=True).start()

    def recon(self):
        cfg = get_config()
        print(cfg)
        recon_time = cfg['personality']['recon_time']
        max_inactive = cfg['personality']['max_inactive_scale']
        recon_mul = cfg['personality']['recon_inactive_multiplier']
        channels = cfg['personality']['channels']

 


        if not channels:
            self._current_channel = 0
            logging.debug("RECON %ds", recon_time)
            self.run('wifi.recon.channel clear')
        else:
            logging.debug("RECON %ds ON CHANNELS %s", recon_time, ','.join(map(str, channels)))
            try:
                self.run('wifi.recon.channel %s' % ','.join(map(str, channels)))
            except Exception as e:
                logging.exception("Error while setting wifi.recon.channels (%s)", e)

        

def load_toml_file(filename):
        """Load toml data from a file. Use toml for dotted, tomlkit for nice formatted"""
        with open(filename) as fp:
            text = fp.read()
        # look for "[main]". if not there, then load
        # dotted toml with toml instead of tomlkit
        if text.find("[main]") != -1:
            return tomlkit.loads(text)
        else:
            print("Converting dotted toml %s: %s" % (filename, text[0:100]))
            import toml
            data = toml.loads(text)
            # save original as a backup
            try:
                backup = filename + ".ORIG"
                os.rename(filename, backup)
                with open(filename, "w") as fp2:
                    tomlkit.dump(data, fp2)
                print("Converted to new format. Original saved at %s" % backup)
            except Exception as e:
                print("Unable to convert %s to new format: %s" % (backup, e))
            return data
    
        return config

    # load the defaults
  


def start(args):

    import time


    config = load_toml_file(args.config)
    print(config)

    

    print("Client è di tipo:", type(Client))
   # client = Client(config)
    client= Client( config,
                        "127.0.0.1" if "hostname" not in config['bettercap'] else config['bettercap']['hostname'],
                        "http" if "scheme" not in config['bettercap'] else config['bettercap']['scheme'],
                        8081 if "port" not in config['bettercap'] else config['bettercap']['port'],
                        "pwnagotchi" if "username" not in config['bettercap'] else config['bettercap']['username'],
                        "pwnagotchi" if "password" not in config['bettercap'] else config['bettercap']['password'])

    
    
    client.session()

    client.start_monitor_mode()

    client.recon()

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