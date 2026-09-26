def main() -> None:
    """Start the production FastAPI application."""
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(".").resolve()))

    import uvicorn
    from src.config import get_available_port, settings

    host = settings.dashboard.host
    port = settings.dashboard.port
    resolved_port = port

    try:
        with __import__("socket").socket(__import__("socket").AF_INET, __import__("socket").SOCK_STREAM) as probe:
            probe.bind((host, port))
    except OSError:
        resolved_port = get_available_port(port)
        print(f"Port {port} is already in use. Falling back to port {resolved_port}.")

    print(f"\n[+] AI Test Automation Dashboard starting...")
    print(f"-> Open in browser: http://localhost:{resolved_port} or http://127.0.0.1:{resolved_port}\n")

    uvicorn.run(
        "src.api.dashboard:app",
        app_dir=".",
        host=host,
        port=resolved_port,
        reload=settings.dashboard.reload,
    )

