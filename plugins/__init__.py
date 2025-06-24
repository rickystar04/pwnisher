import logging
loaded = {}
import os
import glob
import importlib
import queue

import threading

default_path = os.path.join(os.path.dirname(os.path.realpath(__file__)), "default")
database = {}
locks = {}
plugin_event_queues = {}



class PluginEventQueue(threading.Thread):
    def __init__(self, plugin_name):
        try:
            self._worker_thread = threading.Thread.__init__(self, daemon=True)
            self.plugin_name = plugin_name
            self.work_queue = queue.Queue()
            self.queue_lock = threading.Lock()
            self.load_handler = None
            self.keep_going = True
            logging.debug("PLUGIN EVENT QUEUE FOR %s starting %s" % (plugin_name, repr(self.load_handler)))
            self.start()
        except Exception as e:
            logging.exception(e)

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
        print("qui")
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

        print(enabled)

        print(default_path)

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

        #on('loaded')
        #on('config_changed', config)
    except Exception as e:
        logging.exception(repr(e))
