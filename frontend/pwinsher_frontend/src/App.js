import React, { useEffect, useState } from "react";
import "./App.css";

function App() {
  const [aps, setAps] = useState([]);

  useEffect(() => {
    const fetchAccessPoints = async () => {
      try {
        const response = await fetch("http://localhost:8000/api/wifi");
        const data = await response.json();
        console.log("Dati ricevuti:", data);
        setAps(data);
      } catch (e) {
        console.error("Errore nel fetch", e);
      }
    };

    fetchAccessPoints();

    // Se vuoi aggiornare ogni tot secondi, puoi fare così:
    const intervalId = setInterval(fetchAccessPoints, 5000);
    return () => clearInterval(intervalId);
  }, []);

  return (
    <div className="App">
      <div>Reti WIFI trovate:</div>
      <ul>
        {aps.map((ap, index) => (
          <li key={ap.bssid || index}>
            SSID: {ap.ssid}, BSSID: {ap.bssid}, Channel: {ap.channel}, Clients:{" "}
            {ap.clients}
          </li>
        ))}
      </ul>
    </div>
  );
}

export default App;
