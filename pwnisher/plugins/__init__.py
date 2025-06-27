import logging
loaded = {}
import os
import glob
import importlib
import queue
import prctl

import threading

default_path = os.path.join(os.path.dirname(os.path.realpath(__file__)), "default")
database = {}
locks = {}
plugin_event_queues = {}
exitFlag = 0
loaded = {}





def run_once(pqueue, event_name, *args, **kwargs):
    try:
        prctl.set_name("R1_%s_%s" % (pqueue.plugin_name, event_name))
        pqueue.process_event(event_name, *args, *kwargs)
    except Exception as e:
        logging.exception("Thread for %s, %s, %s, %s" % (pqueue.plugin_name, event_name, repr(args), repr(kwargs)))

class PluginEventQueue(threading.Thread):
    def __init__(self, plugin_name):
        try:
            self._worker_thread = threading.Thread.__init__(self, daemon=True)
            
            self.plugin_name = plugin_name
            self.work_queue = queue.Queue()
            self.queue_lock = threading.Lock()
            self.load_handler = None
            self.keep_going = True
            logging.info("PLUGIN EVENT QUEUE FOR %s starting %s" % (plugin_name, repr(self.load_handler)))
            self.start()
        except Exception as e:
            logging.exception(e)
    
    def __del__(self):

        self.keep_going = False

        self._worker_thread.join()

        if self.load_handler:
            self.load_handler.join() 

    def AddWork(self, event_name, *args, **kwargs):
        if event_name == "loaded":
            
            # spawn separate thread, because many plugins use on_load as a "main" loop
            # this way on_load can continue if it needs, while other events get processed
            try:
                cb_name = 'on_%s' % event_name
                callback = getattr(loaded[self.plugin_name], cb_name, None)
                if callback:
                    self.load_handler = threading.Thread(target=run_once,
                                                         args=(self, event_name, *args),
                                                         kwargs=kwargs,
                                                         daemon=True)
                    self.load_handler.start()
                else:
                    self.load_handler = None
            except Exception as e:
                logging.exception(e)
        else:
            self.work_queue.put([event_name, args, kwargs])
    
    def run(self):
        logging.debug("Worker thread starting for %s"%(self.plugin_name))
        prctl.set_name("PLG %s" % self.plugin_name)
        self.process_events()
        logging.info("Worker thread exiting for %s"%(self.plugin_name))
    
    def process_event(self, event_name, *args, **kwargs):
        cb_name = 'on_%s' % event_name
        logging.debug(f"[{self.plugin_name}] process_event: looking for {cb_name}")
        
        plugin = loaded.get(self.plugin_name)
        if plugin is None:
            logging.warning(f"[{self.plugin_name}] process_event: plugin not found in loaded")
            return

        callback = getattr(plugin, cb_name, None)
        if callback:
            logging.debug(f"[{self.plugin_name}] process_event: found callback {cb_name}, calling it with args={args} kwargs={kwargs}")
            try:
                callback(*args, **kwargs)
                logging.debug(f"[{self.plugin_name}] process_event: {cb_name} executed successfully")
            except Exception as e:
                logging.exception(f"[{self.plugin_name}] Error while executing {cb_name}: {e}")
        else:
            logging.debug(f"[{self.plugin_name}] process_event: callback {cb_name} not found or not callable")

    def process_events(self):
        global exitFlag
        plugin_name = self.plugin_name
        work_queue = self.work_queue

        logging.debug(f"[{plugin_name}] process_events: starting event loop")

        while not exitFlag and self.keep_going:
            try:
                logging.debug(f"[{plugin_name}] process_events: waiting for event...")
                data = work_queue.get(timeout=2)
                (event_name, args, kwargs) = data
                logging.debug(f"[{plugin_name}] process_events: got event {event_name} with args={args}, kwargs={kwargs}")
                self.process_event(event_name, *args, **kwargs)
            except queue.Empty:
                logging.debug(f"[{plugin_name}] process_events: no event received (queue empty)")
                continue
            except Exception as e:
                logging.exception(f"[{plugin_name}] process_events: unexpected error: {e}")


class Plugin:
    @classmethod
    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        global loaded, locks

        plugin_name = cls.__module__.split('.')[0]
        plugin_instance = cls()
        logging.debug("loaded plugin %s as %s" % (plugin_name, plugin_instance))
        loaded[plugin_name] = plugin_instance

        for attr_name in plugin_instance.__dir__():
            if attr_name.startswith('on_'):
                cb = getattr(plugin_instance, attr_name, None)
                if cb is not None and callable(cb):
                    locks["%s::%s" % (plugin_name, attr_name)] = threading.Lock()


def load_from_file(filename):
    logging.debug("loading %s" % filename)
    plugin_name = os.path.basename(filename.replace(".py", ""))
    spec = importlib.util.spec_from_file_location(plugin_name, filename)
    instance = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(instance)
    if plugin_name not in plugin_event_queues:
        plugin_event_queues[plugin_name] = PluginEventQueue(plugin_name)
    return plugin_name, instance


def load_from_path(path, enabled=()):
    
    global loaded, database
    logging.debug("loading plugins from %s - enabled: %s" % (path, enabled))
    print(glob.glob(os.path.join(path, "*.py")))
    for filename in glob.glob(os.path.join(path, "*.py")):
        plugin_name = os.path.basename(filename.replace(".py", ""))
        database[plugin_name] = filename
        if plugin_name in enabled:
            try:
                load_from_file(filename)
            except Exception as e:
                logging.warning("error while loading %s: %s" % (filename, e))
                logging.debug(e, exc_info=True)

    return loaded


def load(config):
    try:
        enabled = [name for name, options in config['main']['plugins'].items() if
                   'enabled' in options and options['enabled']]

 

        # load default plugins
        load_from_path(default_path, enabled=enabled)

        # load custom ones
       # custom_path = config['main']['custom_plugins'] if 'custom_plugins' in config['main'] else None
       # if custom_path is not None:
        #    print("prova")
        #    load_from_path(custom_path, enabled=enabled)

        # propagate options
        #for name, plugin in loaded.items():
        #    if name in config['main']['plugins']:
        #        plugin.options = config['main']['plugins'][name]
        #    else:
        #        plugin.options = {}

        on('loaded')
        on('config_changed', config)
    except Exception as e:
        logging.exception(repr(e))

def on(event_name, *args, **kwargs):
    global loaded, plugin_event_queues
    cb_name = 'on_%s' % event_name
    for plugin_name in loaded.keys():
        plugin = loaded[plugin_name]
        callback = getattr(plugin, cb_name, None)

        if callback is None or not callable(callback):
            continue

        if plugin_name not in plugin_event_queues:
            plugin_event_queues[plugin_name] = PluginEventQueue(plugin_name)

        plugin_event_queues[plugin_name].AddWork(event_name, *args, **kwargs)

def one(plugin_name, event_name, *args, **kwargs):
    global loaded, plugin_event_queues
    if plugin_name in loaded:
        plugin = loaded[plugin_name]
        cb_name = 'on_%s' % event_name
        callback = getattr(plugin, cb_name, None)
        if callback is not None and callable(callback):
            if plugin_name not in plugin_event_queues:
                plugin_event_queues[plugin_name] = PluginEventQueue(plugin_name)

            plugin_event_queues[plugin_name].AddWork(event_name, *args, **kwargs)
