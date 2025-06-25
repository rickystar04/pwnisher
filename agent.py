from bettercap import Client
import asyncio
import logging
import time
import threading

class Agent(Client):
    def __init__(self, config):

        Client.__init__(self,
                        "127.0.0.1" if "hostname" not in config['bettercap'] else config['bettercap']['hostname'],
                        "http" if "scheme" not in config['bettercap'] else config['bettercap']['scheme'],
                        8081 if "port" not in config['bettercap'] else config['bettercap']['port'],
                        "user" if "username" not in config['bettercap'] else config['bettercap']['username'],
                        "pass" if "password" not in config['bettercap'] else config['bettercap']['password']
        )

        self.config = config

    def get_config(self):
        return self.config
    
    def setup_events(self):
        logging.info("connecting to %s ...", self.url)

        for tag in self.config['bettercap']['silence']:
            try:
                print(self.config)
                self.run('events.ignore %s' % tag, verbose_errors=False)
            except Exception:
                pass

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
        mon_iface = self.config["main"]['iface']
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

    def start(self):
        self._wait_bettercap()
        self.setup_events()
        self.start_monitor_mode()
        self.start_event_polling()
        self.start_session_fetcher()
        # print initial stats
        self.next_epoch()
        self.set_ready()


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
