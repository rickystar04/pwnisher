# main.py
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from threading import Thread
import time

# Importa la tua classe Client
from bettercap import Client
from config import load_config  # ipotetico file config

# Variabile globale condivisa
captured_aps = []

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/api/wifi")
def get_wifi():
    return {"aps": captured_aps}


# Funzione che fa girare il tuo Client
def start_capture():
    config = load_config()
    client = Client(config)

    while True:
        # qui aggiorni la lista condivisa
        new_aps = client.get_access_points()  # tua funzione
        if new_aps:
            captured_aps.clear()
            captured_aps.extend(new_aps)
        time.sleep(5)

# Avvia il thread all'avvio
@app.on_event("startup")
def startup_event():
    t = Thread(target=start_capture, daemon=True)
    t.start()
