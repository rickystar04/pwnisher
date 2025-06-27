#!/bin/bash

# Avvia Bettercap in background e salva il suo PID
sudo bettercap -eval "api.rest.username user; api.rest.password pass; set api.rest.websocket true; api.rest on;" > /tmp/bettercap.log 2>&1 &
BETTERCAP_PID=$!

# Funzione per terminare Bettercap quando lo script viene interrotto
cleanup() {
    echo -e "\nInterruzione rilevata. Termino Bettercap (PID $BETTERCAP_PID)..."
    sudo kill "$BETTERCAP_PID"
    exit 0
}

# Cattura SIGINT (Ctrl+C) e SIGTERM per chiamare cleanup
trap cleanup SIGINT SIGTERM

# Attendi che l'API sia disponibile
timeout=10
while ! curl -s http://127.0.0.1:8081/api/session > /dev/null && [ $timeout -gt 0 ]; do
    sleep 1
    timeout=$((timeout - 1))
done

if [ $timeout -eq 0 ]; then
    echo "Bettercap non ha avviato l'API REST su 127.0.0.1:8081"
    sudo kill "$BETTERCAP_PID"
    exit 1
fi

echo "BETTERCAP AVVIATO CORRETTAMENTE"
sleep 3

# Avvia il tuo programma
./pwnisher_start

# Quando il programma termina, kill Bettercap se è ancora attivo
sudo kill "$BETTERCAP_PID"
