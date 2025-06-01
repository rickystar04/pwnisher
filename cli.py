import argparse
from bettercap import Client, start
import os


def cli():
    #Client.__init__(                        "127.0.0.1" if "hostname" not in config['bettercap'] else config['bettercap']['hostname'],
     #                  "http" if "scheme" not in config['bettercap'] else config['bettercap']['scheme'],
     #                 8081 if "port" not in config['bettercap'] else config['bettercap']['port'],
      #                 "pwnagotchi" if "username" not in config['bettercap'] else config['bettercap']['username'],
     #                  "pwnagotchi" if "password" not in config['bettercap'] else config['bettercap']['password'])
    base_dir = os.path.dirname(os.path.abspath(__file__))

    # Costruisci il path al file di configurazione
    default_config_path = os.path.join(base_dir, 'default.toml')
    print("PROVA")
    parser = argparse.ArgumentParser(prog="pwnagotchi")
    parser.add_argument(
        '-C', '--config',
        action='store',
        dest='config',
        default=default_config_path,
        help='Main configuration file.'
    )

    parser.add_argument(
        '-m', '--manual',
        action='store_true',
        dest='manual',
        help='Active manual mode.'
    )

    args = parser.parse_args()

    print(args)

    if args.config:

        print(f"Using config file: {args.config}")
        start(args)
        

    else:
        print("Altro argument")

    

cli()