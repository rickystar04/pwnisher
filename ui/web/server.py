import threading
import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from ui.web.handler import Handler  # handler che aggiunge le route

class Server:
    def __init__(self, agent, config):
        self._config = config['web']
        self._enabled = self._config['enabled']
        self._port = self._config['port']
        self._address = self._config['address']
        self._origin = self._config.get('origin', 'http://localhost:3000')  # React frontend
        self._agent = agent

        if self._enabled:
            logging.info("🧵 Avvio del WebServer API in un nuovo thread")
            self._thread = threading.Thread(target=self._http_serve, name="FastAPIWebServer", daemon=True)
            self._thread.start()

    def _http_serve(self):
        if self._address is None:
            logging.warning("⚠️ Nessun indirizzo IP valido, server non avviato")
            return

        app = FastAPI()

        # Configura CORS per permettere al React frontend di accedere all’API
        app.add_middleware(
            CORSMiddleware,
            #allow_origins=[self._origin],
            allow_origins=["http://localhost:3000"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

        # Passa app e agent al tuo handler personalizzato che registra le route
        Handler(self._config, self._agent, app)

        import uvicorn
        logging.info(f"🚀 API REST in esecuzione su http://{self._address}:{self._port}")
        uvicorn.run(app, host=self._address, port=self._port, log_level="info")
