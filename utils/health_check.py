"""
Health Check — Verify Ollama is running and required models are available.
Fails fast with clear error messages instead of cryptic exceptions mid-execution.
"""

import logging
from typing import Optional

logger = logging.getLogger("antigravity.health")


def check_ollama_health(host: str = "http://localhost:11434") -> dict:
    """
    Check if Ollama is running and accessible.
    
    Returns:
        dict with 'healthy' bool, 'version' str, 'error' str
    """
    try:
        import httpx
        response = httpx.get(f"{host}/api/version", timeout=5.0)
        if response.status_code == 200:
            data = response.json()
            return {
                "healthy": True,
                "version": data.get("version", "unknown"),
                "error": "",
            }
        return {
            "healthy": False,
            "version": "",
            "error": f"Ollama returned HTTP {response.status_code}",
        }
    except httpx.ConnectError:
        return {
            "healthy": False,
            "version": "",
            "error": f"Cannot connect to Ollama at {host}. Is it running? Start with: ollama serve",
        }
    except Exception as e:
        return {
            "healthy": False,
            "version": "",
            "error": f"Health check failed: {str(e)}",
        }


def list_available_models(host: str = "http://localhost:11434") -> list[str]:
    """Get list of models currently available in Ollama."""
    try:
        import httpx
        response = httpx.get(f"{host}/api/tags", timeout=10.0)
        if response.status_code == 200:
            data = response.json()
            return [m["name"] for m in data.get("models", [])]
        return []
    except Exception:
        return []


def verify_models(
    required_models: list[str],
    host: str = "http://localhost:11434",
) -> dict:
    """
    Verify that required models are pulled and available.
    
    Returns:
        dict with 'all_available' bool, 'available' list, 'missing' list
    """
    available = list_available_models(host)
    
    # Normalize model names for comparison (handle tag variants)
    available_base = set()
    for m in available:
        available_base.add(m)
        # Also add without tag suffix for flexible matching
        if ":" in m:
            available_base.add(m.split(":")[0])
    
    found = []
    missing = []
    for model in required_models:
        model_base = model.split(":")[0] if ":" in model else model
        if model in available_base or model_base in available_base:
            found.append(model)
        else:
            missing.append(model)
    
    result = {
        "all_available": len(missing) == 0,
        "available": found,
        "missing": missing,
        "total_models": len(available),
    }
    
    if missing:
        logger.warning(f"Missing models: {missing}")
        logger.warning("Pull them with: " + " && ".join(f"ollama pull {m}" for m in missing))
    else:
        logger.info(f"All required models available: {found}")
    
    return result


def full_health_check(
    required_models: list[str],
    host: str = "http://localhost:11434",
) -> dict:
    """
    Complete health check: Ollama connectivity + model availability.
    
    Returns comprehensive status dict.
    """
    health = check_ollama_health(host)
    
    if not health["healthy"]:
        return {
            "status": "unhealthy",
            "ollama": health,
            "models": {"all_available": False, "available": [], "missing": required_models},
            "ready": False,
        }
    
    models = verify_models(required_models, host)
    
    return {
        "status": "healthy" if models["all_available"] else "degraded",
        "ollama": health,
        "models": models,
        "ready": models["all_available"],
    }
