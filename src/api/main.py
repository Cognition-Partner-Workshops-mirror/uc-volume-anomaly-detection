"""Basic Python API using FastAPI for the Volume Anomaly Detection service."""

from fastapi import FastAPI, Query
from pydantic import BaseModel, Field

app = FastAPI(
    title="Volume Anomaly Detection API",
    description="API para deteccao de anomalias em volumes de transacoes",
    version="1.0.0",
)


class HealthResponse(BaseModel):
    status: str
    version: str


class TransactionVolume(BaseModel):
    service: str = Field(..., description="Nome do servico")
    timestamp: str = Field(..., description="Timestamp ISO 8601")
    volume: int = Field(..., ge=0, description="Volume de transacoes")


class AnomalyResponse(BaseModel):
    service: str
    is_anomaly: bool
    score: float
    message: str


class DetectionConfig(BaseModel):
    sensitivity: int = Field(default=5, ge=1, le=10, description="Sensibilidade (1-10)")
    baseline_window_days: int = Field(default=30, ge=1, le=90)


# In-memory storage for demonstration
_transaction_history: list[TransactionVolume] = []
_config = DetectionConfig()


@app.get("/health", response_model=HealthResponse)
def health_check():
    """Verifica o status da API."""
    return HealthResponse(status="healthy", version="1.0.0")


@app.get("/transactions", response_model=list[TransactionVolume])
def list_transactions(
    service: str | None = Query(default=None, description="Filtrar por servico"),
    limit: int = Query(default=100, ge=1, le=1000),
):
    """Lista as transacoes registradas."""
    results = _transaction_history
    if service:
        results = [t for t in results if t.service == service]
    return results[-limit:]


@app.post("/transactions", response_model=TransactionVolume, status_code=201)
def record_transaction(transaction: TransactionVolume):
    """Registra um novo volume de transacao."""
    _transaction_history.append(transaction)
    return transaction


@app.post("/detect", response_model=AnomalyResponse)
def detect_anomaly(transaction: TransactionVolume):
    """Analisa se o volume informado representa uma anomalia."""
    service_history = [
        t.volume for t in _transaction_history if t.service == transaction.service
    ]

    if len(service_history) < 5:
        return AnomalyResponse(
            service=transaction.service,
            is_anomaly=False,
            score=0.0,
            message="Dados insuficientes para deteccao (minimo 5 registros)",
        )

    mean = sum(service_history) / len(service_history)
    variance = sum((x - mean) ** 2 for x in service_history) / len(service_history)
    std_dev = variance**0.5

    if std_dev == 0:
        z_score = 0.0
    else:
        z_score = abs(transaction.volume - mean) / std_dev

    threshold = (11 - _config.sensitivity) * 0.5
    is_anomaly = z_score > threshold

    return AnomalyResponse(
        service=transaction.service,
        is_anomaly=is_anomaly,
        score=round(z_score, 2),
        message=(
            f"Anomalia detectada (z-score: {z_score:.2f} > threshold: {threshold:.1f})"
            if is_anomaly
            else f"Volume normal (z-score: {z_score:.2f})"
        ),
    )


@app.get("/config", response_model=DetectionConfig)
def get_config():
    """Retorna a configuracao atual de deteccao."""
    return _config


@app.put("/config", response_model=DetectionConfig)
def update_config(config: DetectionConfig):
    """Atualiza a configuracao de deteccao."""
    global _config
    _config = config
    return _config


@app.delete("/transactions", status_code=204)
def clear_transactions():
    """Limpa o historico de transacoes."""
    _transaction_history.clear()
