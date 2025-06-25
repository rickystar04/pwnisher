import argparse
from bettercap import Client, start
from agent import Agent
import time
import tomlkit
import os
import logging


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


def cli():


    def auto_mode(agent):
        print("Auto mode is active")
        agent.start()
        while True:
            try:
                # recon on all channels
                agent.recon()
                # get nearby access points grouped by channel
                channels = agent.get_access_points_by_channel()


                # for each channel
                for ch, aps in channels:
                    time.sleep(1)
                    client.set_channel(ch)

                    #if not agent.is_stale() and agent.any_activity():
                    logging.info("%d access points on channel %d" % (len(aps), ch))

                    # for each ap on this channel
                    for ap in aps:
                        # send an association frame in order to get for a PMKID
                        agent.associate(ap)
                        # deauth all client stations in order to get a full handshake
                        for sta in ap['clients']:
                            agent.deauth(ap, sta)
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
        # Implementa la logica per la modalità automatica qui

    def manual_mode():
        print("Manual mode is active")
        # Implementa la logica per la modalità manuale qui
        
    base_dir = os.path.dirname(os.path.abspath(__file__))

    # Costruisci il path al file di configurazione
    default_config_path = os.path.join(base_dir, 'default.toml')
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
    else:
        print("Altro argument")

    config = load_toml_file(args.config)

    
    agent=Agent(config=config)


    auto_mode(agent)
        

    

    


if __name__ == "__main__":
    cli()