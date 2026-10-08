import json
import urllib.error
import urllib.request


def post(config, endpoint, payload):
    if not config["server_url"] or not config["api_key"]:
        raise ValueError("NETDOCTOR_SERVER_URL and NETDOCTOR_API_KEY are required")
    request = urllib.request.Request(
        config["server_url"] + endpoint, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "X-NetDoctor-Key": config["api_key"]},
        method="POST")
    try:
        # The server may finish rule/AI processing before replying to an upload.
        timeout = 120 if endpoint == "/api/v1/measurements" else 10
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"HTTP {exc.code}: {exc.reason}") from exc


def register(config, payload):
    return post(config, "/api/v1/agents/register", payload)


def upload(config, payload):
    return post(config, "/api/v1/measurements", payload)
