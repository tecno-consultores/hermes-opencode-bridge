# locustfile.py
from locust import HttpUser, task, between

class ACPOrchestratorUser(HttpUser):
    # Simula el retraso humano/agente entre peticiones (1 a 3 segundos)
    wait_time = between(1, 3)

    @task(3)
    def check_health(self):
        """Golpea constantemente el endpoint de salud."""
        self.client.get("/health", name="/health")

    @task(1)
    def ping_mcp_messages(self):
        """Envía tráfico JSON-RPC al orquestador para medir la estabilidad bajo carga."""
        payload = {
            "jsonrpc": "2.0",
            "method": "ping",
            "id": 999
        }
        # Interceptamos la respuesta. Nos interesa medir latencia y timeouts, 
        # sin importar si el código HTTP es 404 o 500 (ya que OpenCode no está encendido).
        with self.client.post("/mcp/messages", json=payload, name="/mcp/messages", catch_response=True) as response:
            if response.status_code in [200, 202, 400, 404, 500]:
                response.success()
