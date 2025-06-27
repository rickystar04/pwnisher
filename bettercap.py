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
import glob
import threading

import pwnisher

from time import sleep
from requests.auth import HTTPBasicAuth

import pwnisher.plugins as plugins





logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
)


logging.getLogger("requests").setLevel(logging.WARNING)

requests.adapters.DEFAULT_RETRIES = 5

ping_timeout = 180
ping_interval = 15
max_queue = 10000

min_sleep = 0.5
max_sleep = 5.0

RECOVERY_DATA_FILE = '/root/.pwnagotchi-recovery'


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
    def __init__(self, hostname='localhost', scheme='http', port=8081, username='user', password='pass'):
        self.hostname = hostname
        self.scheme = scheme
        self.port = port
        self.username = username
        self.password = password
        self.url = f"{scheme}://{hostname}:{port}/api"
        self.websocket = f"ws://{username}:{password}@{hostname}:{port}/api"
        self.auth = HTTPBasicAuth(username, password)

        self._history = {}
        self._handshakes={}
        self._last_pwnd = None
        self.ping_interval = 20
        self.ping_timeout = 10
        self.max_queue = None
        self.min_sleep = 2
        self.max_sleep = 10

        self.aps={}



 
    #FUNZIONAVA PRIMA
    def session(self, sess="session"):

        r = requests.get(f"{self.url}/{sess}", auth=self.auth)
        return decode(r)
    

    async def start_websocket(self, consumer):
        print("QUIIIIIIIIIIIIIIIII")

        s = f"{self.websocket}/events"
        while True:
            logging.error("QUIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIII")
            logging.info("[bettercap] creating new websocket...")
            logging.info("[bettercap] connecting to %s", s)
            try:
                async with websockets.connect(
                    s,
                    ping_interval=self.ping_interval,
                    ping_timeout=self.ping_timeout,
                    max_queue=self.max_queue
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
            except ConnectionRefusedError:
                sleep_time = min_sleep + max_sleep*random.random()
                logging.warning('[bettercap] nobody seems to be listening at the bettercap endpoint...')
                logging.warning('[bettercap] retrying connection in {} sec'.format(sleep_time))
                await asyncio.sleep(sleep_time)
                continue
            except OSError:
                logging.warning('connection to the bettercap endpoint failed...')
                pwnisher.restart("AUTO")

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
    



    def get_config(self):
        return self.config


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

def try_view_ap(Client):
    aps = Client.view_aps()
    if not aps:
        print("No access points found.")
        return

    for ap in aps.values():
        print(f"AP: {ap['hostname']} ({ap['mac']}) on channel {ap['channel']}, RSSI: {ap['rssi']} dBm")
        for client in ap['clients']:
            print(f"  Client: {client['mac']} ({client['vendor']}), RSSI: {client['rssi']} dBm")





def start(args):
    config = load_toml_file(args.config)

    pwnisher.config=config

    logging.info("Loaded config: %s", config)

    print(plugins.__file__)
    plugins.load(config)

   

    hostname = config['bettercap'].get('hostname', '127.0.0.1')
    client= Client( config,
                        "127.0.0.1" if "hostname" not in config['bettercap'] else config['bettercap']['hostname'],
                        "http" if "scheme" not in config['bettercap'] else config['bettercap']['scheme'],
                        8081 if "port" not in config['bettercap'] else config['bettercap']['port'],
                        "user" if "username" not in config['bettercap'] else config['bettercap']['username'],
                        "pass" if "password" not in config['bettercap'] else config['bettercap']['password']
    )

    client.setup_events()
    logging.info("Client è di tipo: %s", type(client))
    #client.run("set events.stream false")
    #client.run("set events.logger false")


    

    client.session()

  
    client.start_monitor_mode()

    client.start_event_polling()
    client.start_session_fetcher()

    logging.info("Client è di tipo: %s", type(client))





    """
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
    """

    
    while True:
            try:
                # recon on all channels
                client.recon()
                # get nearby access points grouped by channel
                channels = client.get_access_points_by_channel()


                # for each channel
                for ch, aps in channels:
                    time.sleep(1)
                    client.set_channel(ch)

                    #if not agent.is_stale() and agent.any_activity():
                    logging.info("%d access points on channel %d" % (len(aps), ch))

                    # for each ap on this channel
                    for ap in aps:
                        # send an association frame in order to get for a PMKID
                        client.associate(ap)
                        # deauth all client stations in order to get a full handshake
                        for sta in ap['clients']:
                            client.deauth(ap, sta)
                            time.sleep(1)  # delay to not trigger nexmon firmware bugs

                # An interesting effect of this:
                #
                # From Pwnagotchi's perspective, the more new access points
                # and / or client stations nearby, the longer one epoch of
                # its relative time will take ... basically, in Pwnagotchi's universe,
                # Wi-Fi electromagnetic fields affect time like gravitational fields
                # affect ours ... neat ^_^
                #agent.next_epoch()

                #if grid.is_connected():
                 #   plugins.on('internet_available', agent)

            except Exception as e:
                if str(e).find("wifi.interface not set") > 0:
                    logging.exception("main loop exception due to unavailable wifi device, likely programmatically disabled (%s)", e)
                    logging.info("sleeping 60 seconds then advancing to next epoch to allow for cleanup code to trigger")
                    time.sleep(60)
                    #agent.next_epoch()
                else:
                    logging.exception("main loop exception (%s)", e)
    